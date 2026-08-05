# Dirty Living-Economy Worktree Salvage Design

## Goal

Preserve and classify every uncommitted change in the registered `feature/living-economy-map` worktree, then selectively port still-valid numeric-grounding, entrepreneurship, replay, reporting, and UI behavior onto current `main` without reviving superseded map code.

## Current boundary

The committed living-economy-map feature has already been superseded by the interactive living-city work on `main`. Its registered worktree is not clean: 31 tracked files contain roughly 1,320 additions and 121 deletions, and three files are untracked. The changes mix generated dashboard assets, run-resume hydration, entrepreneurship activation, numeric narrative grounding, report/news redaction, replay behavior, and tests. The branch is far behind current `main` and produces broad conflicts, so branch-level merging cannot preserve intent safely.

## Considered approaches

### 1. Immutable snapshot, hunk inventory, and selective ports — selected

Capture the dirty state before modification, classify every file and hunk against current `main`, and port coherent behavior on new branches with tests. This maximizes preservation while allowing obsolete UI and generated artifacts to be retired explicitly.

### 2. Commit all changes and merge the branch

This preserves bytes in Git but entangles unrelated behavior, stale generated bundles, and superseded components. It would produce an unreviewable conflict resolution.

### 3. Discard the worktree because the map feature landed

This would lose unique numeric-grounding, activation, replay, and report work that is not present on current `main`.

## Preservation package

Before any checkout, formatting command, dependency install, or build runs in the dirty worktree, create a preservation package containing:

- worktree path, branch tip, merge bases, Git version, and UTC timestamp;
- porcelain status with rename-safe paths;
- binary-capable tracked diff and staged diff;
- byte-for-byte copies and SHA-256 hashes of untracked files;
- a file inventory identifying generated assets separately from authored source;
- a secret scan result for the captured material.

The package lives outside the repository and receives its own checksum manifest. It must be restorable onto the recorded branch tip. No cleanup occurs until a restore rehearsal proves the package.

## Classification model

Every changed path receives one disposition:

- **Equivalent:** current `main` already implements the same contract with equal or stronger tests.
- **Superseded:** the old component or behavior was intentionally replaced and must not return.
- **Portable:** unique behavior is still required and can be implemented against current interfaces.
- **Needs design:** intent is valuable but conflicts with current semantics or product boundaries.
- **Generated:** rebuild output follows an accepted source change and is never treated as the source of truth.

The inventory records evidence for the disposition: matching commit, current file/function, test coverage, or an explicit incompatibility.

## Port boundaries

Portable work is split into independent changes:

1. **Resume hydration:** terminal report discovery and stale `running` normalization, reconciled with current run-controller and hosted-supervisor semantics.
2. **Entrepreneurship activation:** forward-only opt-in activation, bounded formations, pre-seed and merger lifecycle guards, and replay-safe legacy behavior.
3. **Numeric grounding:** authoritative structured numeric facts, bounded reserved-belief updates, rejection or redaction of unsupported model arithmetic, and retention of raw governed provider records for audit.
4. **Public presentation:** unit-preserving belief formatting and explicit warnings for historical memories, model output, news, replay, and reports.
5. **Generated dashboard bundle:** rebuilt only after accepted source ports pass.

These ports must not depend on the obsolete living-map branch architecture. Each starts from current `main` and carries only its own source and tests.

## Numeric-grounding contract

Engine state and metrics remain authoritative. Model-authored public narrative may repeat numeric tokens present in the bounded structured source but may not derive or invent arithmetic. Historical memories remain claims and may be stale. Reserved trust, sentiment, and inflation beliefs require an existing baseline and a configured maximum step. Raw provider input/output remains in governed audit storage; public projections and reports use the sanitized representation after the forward-only activation boundary.

Compatibility tests must prove that runs predating the boundary replay unchanged and that scripted engine updates are not mistaken for model-authored belief changes.

## Entrepreneurship contract

Activation is allowed only on a paused source run and begins at the next untouched decision boundary. Existing active configuration is idempotent. Formation capacity, age, capital, risk, competition, financing, IP, and merger guards remain deterministic and engine-owned. Prompt context can expose qualified opportunities but cannot invent financing or merger terms. Historical persisted formations remain replayable.

## Verification and disposition

Each portable unit follows test-first implementation, focused regressions, compatibility/replay checks, full Python shards, dashboard tests/build where applicable, and a real Chrome smoke for public presentation. After all units are accepted or rejected, the inventory must account for every original path and untracked file. Only then may the old worktree be archived or removed under a separately reviewed operation.

## Failure handling

If snapshot restoration, secret scanning, or hunk classification is incomplete, the worktree remains untouched. A port that changes historical replay or contradicts current semantics is rejected or redesigned; it is not made compatible by weakening tests. Generated asset differences never justify porting stale source.

## Acceptance evidence

Completion requires a verified preservation package, a disposition matrix covering every changed path, reviewed commits for each accepted portable unit, test and browser receipts, and an explicit record of superseded or rejected material. A clean old worktree without that accounting is data loss, not completion.

## Out of scope

- Re-merging the committed living-map feature.
- Deleting the worktree or preservation package during salvage.
- Treating model narrative as authoritative numeric state.
- Bundling recovery-branch semantics into the salvage ports.

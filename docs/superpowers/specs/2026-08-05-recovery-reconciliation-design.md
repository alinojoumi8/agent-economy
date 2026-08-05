# Supply and Workforce Recovery Reconciliation Design

## Goal

Reconcile the unique recovery work on `codex/reconcile-release` with current `main`, preserving compatibility and producing a reviewable implementation whose acceptance claim is backed by a completed receipt, database integrity, ledger reconciliation, and exact replay.

## Current boundary

The recovery branch is clean and contains 26 commits not patch-equivalent to `main`. It is 40 commits behind current `main`; a synthetic merge reports 17 conflict markers across ten overlapping areas. Current `main` already contains forward-only supply-recovery activation and workforce-recovery tests, while the branch adds deeper economics, bounded recovery checkpoints, recovery reporting, and terminal receipt contracts. The original branch therefore cannot be merged wholesale or treated as entirely absent functionality.

The historical candidate database `820e5bf35e.db` is evidence from an older commit boundary. It may be audited read-only, but branch reconciliation changes invalidate it as final evidence for the new tree unless the receipt contract explicitly proves compatibility and commit eligibility.

## Considered approaches

### 1. Preserve the branch and port logical commit groups onto current `main` — selected

Create a new clean worktree from current `main`, retain `codex/reconcile-release` unchanged, and port behavior in dependency order. Compare every port with functionality already on `main`, add focused regressions before resolving overlapping code, and produce a new acceptance run on the reconciled head.

### 2. Rebase the original branch in place

This keeps the original commit sequence but risks obscuring the known-good branch, complicates recovery from conflict mistakes, and makes it harder to distinguish upstream equivalents from unique work.

### 3. Merge the branch and resolve conflicts in one commit

This would retain graph history but creates an oversized review surface and weakens causal attribution between economic rules, retention safety, reporting, and receipt validation.

## Functional decomposition

The port is divided into four independently reviewable layers:

1. **Recovery economics:** demand-unit correction, inventory-aware shopping, viable hiring, wage/pay-interval consistency, recapitalization, stockout recovery, and deterministic target convergence.
2. **Lifecycle safety:** stale offer/application rejection, acquirer bankruptcy guards, merger timing and marker retention, and stale hosted-job reconciliation.
3. **Checkpoint retention:** bounded recovery checkpoints with catalog/file consistency, no broad wildcard deletion, and recovery-safe resume semantics.
4. **Acceptance reporting:** `reports/supply_recovery.py`, the governed recovery profile, terminal evidence validation, machine-readable receipt, reviewer-readable report, and replay eligibility.

Each layer consumes the current semantics/version guards. No port may silently change stored semantics 1–7 behavior or upgrade historical databases in place.

## Conflict-resolution rule

For every overlapping function, the current `main` implementation is the compatibility baseline and the branch is a source of candidate behavior. The resolution record must identify:

- the competing commits and files;
- the invariant or test that decides the result;
- whether current `main`, the branch, or a synthesized implementation wins;
- the focused regression proving the decision;
- replay and migration impact.

Conflict resolution by choosing an entire side without this record is prohibited.

## Recovery acceptance contract

A recovery run passes only when all of the following are true at the configured horizon:

- the persisted run status is terminal and no phase is partially active;
- target headcount and governed supply availability converge under the receipt thresholds;
- no stale pending applications, offers, recovery jobs, or lifecycle markers remain;
- recovery actions use actual wages, currencies, inventory, and demand units;
- all currencies and required system accounts reconcile exactly;
- SQLite immutable `quick_check` succeeds and no unexpected WAL/SHM sidecars remain;
- required checkpoint files match their catalog and retained manifests;
- the machine-readable receipt validates its own source hashes and configuration;
- an offline replay consumes recorded responses once, dispatches no live call, reaches the same terminal tick, and reports no deterministic-table difference.

Healthy intermediate ticks, sampled zero-stockout observations, or a clean SQLite check alone are diagnostic evidence only.

## Historical candidate handling

The historical candidate is first inventoried without write-opening it. Its commit/tree binding, tick/phase, sidecars, receipt state, and hash are recorded. If it cannot satisfy the reconciled receipt contract immutably, it remains labelled diagnostic and is never resumed to manufacture post-change eligibility. A fresh run on the reconciled head becomes the acceptance source.

## Verification layers

- Focused unit tests for each economic and lifecycle rule.
- Checkpoint retention/catalog failure-injection tests.
- Receipt mutation tests that fail closed on missing, stale, or inconsistent evidence.
- Compatibility and migration tests for historical semantics.
- Full Python shards and dashboard gates.
- Governed recovery rehearsal, then the qualifying acceptance run.
- Exact offline replay and artifact-hash verification.

## Failure handling

The new integration branch is disposable; the original branch and historical database remain unchanged. Any semantic ambiguity, receipt failure, replay divergence, or checkpoint mismatch blocks merge. Fixes require a new source run when they alter persisted behavior; receipts are never edited to fit a failed run.

## Acceptance evidence

Completion requires a reconciled commit series on current `main`, a conflict-resolution ledger, green focused and full gates, a terminal source receipt, integrity and checkpoint audits, and an exact replay receipt. Merge readiness and release readiness remain separate: this work may merge without satisfying unrelated external connector or long-horizon production gates.

## Out of scope

- Reusing the historical candidate as eligible evidence without immutable proof.
- Pruning unrelated checkpoints or run data.
- Changing unrelated World OS UI routes.
- Running paid Oracle or 365-day campaigns.

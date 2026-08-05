# Repository Publication and Dependency Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the verified local `main` stack by fast-forward, then integrate Recharts 3.10.1 and TanStack React Query 5.101.4 as separately tested dependency changes.

**Architecture:** Perform all publication work in an isolated worktree created from the current local `main`. Record a deterministic preflight and test receipt before pushing, then apply each dependency head independently so failures remain attributable and reversible. Preserve every safety branch, registered worktree, untracked run artifact, and release gate.

**Tech Stack:** Git, GitHub remote refs, Python 3.11/3.12, pytest, Node/npm, React 19, Vite, Playwright Chromium.

## Global Constraints

- Never force-push, rewrite `origin/main`, delete a branch/worktree, or stage `data/`, `env`, or `graphify-out/`.
- Fetch immediately before every remote mutation and require `origin/main` to be an ancestor of the candidate head.
- Treat GitHub authentication, branch protection, billing, and CI as external state; record blockers exactly and never claim a check that did not execute.
- Apply PR 39 and PR 40 independently and preserve unrelated lockfile entries.
- A local test pass does not prove publication; verify remote containment after push.
- Publication and dependency integration do not authorize tagging, deployment, live inference, or public-readiness claims.

---

## File structure

- Create: `docs/releases/2026-08-05-publication.md` — exact branch, command, test, remote, and disposition receipt.
- Modify: `dashboard/package.json` — Recharts version only, when applying PR 39.
- Modify: `dashboard/package-lock.json` — exact resolved dependency updates from PRs 39 and 40.
- Verify: `.github/workflows/ci.yml` — source of the maintained Python/dashboard commands; do not modify unless the commands are demonstrably stale.
- Verify: `server/static/` — committed dashboard bundle freshness after each accepted dependency update.

### Task 1: Create an isolated publication worktree and record preflight

**Files:**
- Create: `docs/releases/2026-08-05-publication.md`
- Verify: `.gitignore`

**Interfaces:**
- Consumes: approved publication design, current local `main`, `origin/main`, registered worktrees.
- Produces: `codex/publish-20260805` and a preflight receipt whose `publication_head` and `origin_head` values are immutable for the next task.

- [ ] **Step 1: Refresh remote state without modifying source files**

Run:

```bash
git fetch --prune origin
git status --short --branch
git rev-list --left-right --count main...origin/main
git worktree list --porcelain
```

Expected: the tracked tree is clean; the right-hand divergence count is `0`; untracked protected paths are listed but untouched. If the right-hand count is nonzero, stop this plan and reconcile the new remote commits first.

- [ ] **Step 2: Prove fast-forward containment**

Run:

```bash
git merge-base --is-ancestor origin/main main
git log --reverse --format='%H %s' origin/main..main
git diff --check origin/main..main
```

Expected: the ancestry command exits `0`, the log contains every unpublished local commit in order, and the diff check prints nothing.

- [ ] **Step 3: Create the isolated worktree using the required worktree skill**

Run after invoking `superpowers:using-git-worktrees`:

```bash
git worktree add .worktrees/publish-20260805 -b codex/publish-20260805 main
git -C .worktrees/publish-20260805 status --short --branch
```

Expected: the new worktree is clean and points at the same commit as `main`.

- [ ] **Step 4: Write the publication receipt header**

Create `docs/releases/2026-08-05-publication.md` with these sections in order: title, repository/branch identity, pre-publication Git identity, unpublished commits, verification table, remote publication, and branch disposition. Populate the identity fields with the literal stdout from:

```bash
git rev-parse HEAD
git rev-parse origin/main
git rev-list --left-right --count HEAD...origin/main
git log --reverse --format='- `%H` %s' origin/main..HEAD
```

The receipt must name repository `alinojoumi8/agent-economy`, branch `codex/publish-20260805`, tracked state `clean`, and protected primary-worktree paths `data/`, `env`, and `graphify-out/`. Initialize the verification table with columns `Gate`, `Command`, and `Result`; initialize remote status/head as `not_run`; initialize branch disposition with columns `Branch`, `Relationship to published head`, and `Action`. Use `apply_patch` to record the observed literal values and review the file before committing it.

- [ ] **Step 5: Commit only the preflight receipt**

Run:

```bash
git add docs/releases/2026-08-05-publication.md
git diff --cached --check
git commit -m "docs: record repository publication preflight"
```

Expected: one documentation file is committed; protected paths and other worktrees remain unchanged.

### Task 2: Run the exact local publication gate

**Files:**
- Modify: `docs/releases/2026-08-05-publication.md`
- Verify: `.github/workflows/ci.yml`
- Verify: `requirements.lock`
- Verify: `dashboard/package-lock.json`

**Interfaces:**
- Consumes: Task 1 publication branch and receipt.
- Produces: a test-complete publication head; no remote mutation yet.

- [ ] **Step 1: Install from committed lockfiles**

Run from `.worktrees/publish-20260805`:

```bash
.venv/bin/python -m pip check
(cd dashboard && npm ci)
```

Expected: `pip check` reports no broken requirements and `npm ci` exits `0` without editing `package-lock.json`.

- [ ] **Step 2: Run all eight deterministic Python shards**

Run all eight indices:

```bash
for AE_CI_SHARD_INDEX in 0 1 2 3 4 5 6 7; do
  .venv/bin/python -m pytest tests/ -q -p scripts.pytest_shard --ci-shard-index "$AE_CI_SHARD_INDEX" --ci-shard-count 8 || exit 1
done
```

Expected: every shard exits `0`; environment-gated skips are recorded by name and are not presented as passes.

- [ ] **Step 3: Run the complete dashboard gate**

Run:

```bash
(
  cd dashboard
  npm test
  npm run typecheck
  npm run licenses:check
  npm audit --audit-level=high
  npm run test:e2e -- --project=chromium
  npm run build
)
```

Expected: all commands exit `0`; the build succeeds; the audit reports zero high-severity vulnerabilities.

- [ ] **Step 4: Verify generated bundle and tracked cleanliness**

Run:

```bash
git status --short
git diff --check
```

Expected: no unexplained tracked changes. If the repository contract requires a refreshed `server/static/` bundle, rebuild it with the existing repository command, rerun the dashboard gate, and commit only the deterministic bundle change.

- [ ] **Step 5: Perform the real Chrome application smoke**

Start the built server with the maintained local run profile, open Google Chrome, and verify:

```text
Overview loads; run status and tick agree with the API; People opens; Communications opens;
Investigations loads; no page error, console error, request failure, or HTTP 5xx occurs.
```

Record the exact run ID, Chrome version, start command, URLs, and error counts in the receipt. Do not run live MiniMax unless separately authorized.

- [ ] **Step 6: Record literal results and commit the receipt**

Update the verification table with command, pass/fail, counts, skips, duration, and artifact hashes where applicable. Then run:

```bash
git add docs/releases/2026-08-05-publication.md server/static
git diff --cached --check
git commit -m "docs: record publication verification"
```

Stage `server/static` only if Step 4 proved an intentional deterministic refresh.

### Task 3: Publish the verified local stack

**Files:**
- Modify: `docs/releases/2026-08-05-publication.md`

**Interfaces:**
- Consumes: exact green head from Task 2.
- Produces: remote containment proof or an explicit external blocker.

- [ ] **Step 1: Re-fetch and re-prove fast-forward safety**

Run:

```bash
git fetch --prune origin
git merge-base --is-ancestor origin/main HEAD
git rev-list --left-right --count HEAD...origin/main
```

Expected: `origin/main` is an ancestor and the right-hand count is `0`. Any new remote commit stops the push.

- [ ] **Step 2: Verify the push target**

Run:

```bash
git remote get-url origin
git status --short --branch
```

Expected: the URL is `https://github.com/alinojoumi8/agent-economy.git` and the tracked tree is clean.

- [ ] **Step 3: Push without force**

Run:

```bash
git push origin HEAD:main
```

Expected: a fast-forward update. Authentication, protection, or billing failures are recorded verbatim in sanitized form and end this task without retrying destructively.

- [ ] **Step 4: Verify remote containment independently**

Run:

```bash
git fetch origin main
git rev-parse HEAD
git rev-parse origin/main
git merge-base --is-ancestor HEAD origin/main
```

Expected: the local verified head is contained in `origin/main`.

- [ ] **Step 5: Record and commit publication outcome**

Set the receipt status to `passed` only after Step 4. If blocked, use `blocked` and state the external condition. Commit:

```bash
git add docs/releases/2026-08-05-publication.md
git commit -m "docs: record repository publication outcome"
git push origin HEAD:main
```

Expected: the receipt commit is also contained in `origin/main`.

### Task 4: Integrate Recharts 3.10.1 independently

**Files:**
- Modify: `dashboard/package.json`
- Modify: `dashboard/package-lock.json`
- Modify: `server/static/` only through the deterministic build pipeline.
- Test: `dashboard/tests/*.test.js`
- Test: `dashboard/tests/e2e/*.spec.ts`

**Interfaces:**
- Consumes: published current `main`, remote PR 39 head.
- Produces: one Recharts-only dependency commit with dashboard evidence.

- [ ] **Step 1: Create an isolated dependency branch**

Run:

```bash
git fetch origin refs/pull/39/head
git switch -c codex/recharts-3.10.1 main
git show --stat --oneline FETCH_HEAD
```

Expected: the fetched commit changes only the dashboard manifest and lockfile.

- [ ] **Step 2: Apply the dependency commit**

Run:

```bash
git cherry-pick FETCH_HEAD
git diff main...HEAD -- dashboard/package.json dashboard/package-lock.json
```

Expected: Recharts changes from `3.9.2` to `3.10.1`; unrelated dependencies do not move.

- [ ] **Step 3: Run the dashboard dependency gate**

Run:

```bash
(
  cd dashboard
  npm ci
  npm test
  npm run typecheck
  npm run licenses:check
  npm audit --audit-level=high
  npm run test:e2e -- --project=chromium
  npm run build
)
```

Expected: all commands pass and the audit reports zero high-severity vulnerabilities.

- [ ] **Step 4: Record deterministic bundle output**

The preceding `npm run build` is the maintained static rebuild. Run:

```bash
git status --short
git diff --check
git add dashboard/package.json dashboard/package-lock.json server/static
git commit --amend --no-edit
```

The preceding maintained build determines whether `server/static` changes; `git add server/static` records that result without manufacturing output. Expected: one coherent Recharts update.

- [ ] **Step 5: Publish through the normal protected workflow**

Push the branch and open or update a PR; do not merge until GitHub checks actually execute. Record the PR URL and checks in the publication receipt.

### Task 5: Integrate TanStack React Query 5.101.4 independently

**Files:**
- Modify: `dashboard/package-lock.json`
- Verify: `dashboard/package.json`
- Modify: `server/static/` only through the deterministic build pipeline.
- Test: `dashboard/tests/*.test.js`
- Test: `dashboard/tests/e2e/*.spec.ts`

**Interfaces:**
- Consumes: published current `main`, remote PR 40 head.
- Produces: one React Query lock update with dashboard evidence.

- [ ] **Step 1: Create an isolated dependency branch**

Run:

```bash
git fetch origin refs/pull/40/head
git switch -c codex/react-query-5.101.4 main
git show --stat --oneline FETCH_HEAD
```

Expected: the fetched patch updates the resolved React Query package and lock metadata.

- [ ] **Step 2: Apply and inspect the lockfile patch**

Run:

```bash
git cherry-pick FETCH_HEAD
git diff main...HEAD -- dashboard/package.json dashboard/package-lock.json
```

Expected: `dashboard/package.json` retains its compatible declared range and the lockfile resolves `@tanstack/react-query` 5.101.4 without unrelated package churn.

- [ ] **Step 3: Run the complete dashboard dependency gate**

Run:

```bash
(
  cd dashboard
  npm ci
  npm test
  npm run typecheck
  npm run licenses:check
  npm audit --audit-level=high
  npm run test:e2e -- --project=chromium
  npm run build
)
```

Expected: every command passes independently of the Recharts branch.

- [ ] **Step 4: Publish through the normal protected workflow**

Stage `dashboard/package-lock.json` and any deterministic `server/static` diff emitted by the maintained build, amend the dependency commit, push the branch, and open or update its PR. Record the PR URL and checks; do not infer CI from mergeability.

```bash
git status --short
git diff --check
git add dashboard/package-lock.json server/static
git commit --amend --no-edit
git push --set-upstream origin codex/react-query-5.101.4
```

### Task 6: Verify combined main and classify remaining branches

**Files:**
- Modify: `docs/releases/2026-08-05-publication.md`

**Interfaces:**
- Consumes: merged dependency PRs and published local stack.
- Produces: final repository state receipt and explicit branch dispositions.

- [ ] **Step 1: Fetch and inspect final main**

Run:

```bash
git fetch --prune origin
git switch main
git pull --ff-only origin main
git status --short --branch
```

Expected: local `main` equals `origin/main`; protected untracked paths remain.

- [ ] **Step 2: Rerun focused dependency and documentation gates**

Run:

```bash
.venv/bin/python -m pytest tests/test_dependency_lock.py tests/test_documentation.py -q
(cd dashboard && npm ci && npm test && npm run typecheck && npm run licenses:check && npm audit --audit-level=high && npm run build)
```

Expected: all commands pass on the combined head.

- [ ] **Step 3: Record branch dispositions without deleting refs**

Use `git merge-base --is-ancestor`, `git cherry`, and tip-to-tip diffs to record:

```text
codex/integrate-origin-20260805: contained safety history; retain.
codex/pre-pull-20260805: historical safety point; retain.
origin/codex/civic-city-semantics12: superseded by current main; close/label remotely only.
feature/living-economy-map: committed feature superseded, dirty worktree protected by its salvage plan.
codex/reconcile-release: unique recovery work protected by its reconciliation plan.
```

- [ ] **Step 4: Commit and publish the final receipt**

Run:

```bash
git add docs/releases/2026-08-05-publication.md
git diff --cached --check
git commit -m "docs: finalize repository publication receipt"
git push origin main
```

Expected: the receipt names exact commits and results, `main` equals `origin/main`, and no branch or worktree was deleted.

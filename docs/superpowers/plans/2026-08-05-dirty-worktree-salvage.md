# Dirty Living-Economy Worktree Salvage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve every uncommitted byte in the registered living-economy-map worktree, classify all changes against current `main`, and selectively port only unique, compatible resume, entrepreneurship, numeric-grounding, and public-presentation behavior.

**Architecture:** Create a restorable snapshot outside the repository before touching the dirty worktree. Build a path-and-hunk disposition matrix, then implement each portable contract on a fresh branch from current `main`; never merge the obsolete feature branch. Keep numeric parsing/sanitization in a pure module, engine activation in `run.py`, and public formatting in focused frontend helpers.

**Tech Stack:** Git worktrees, binary Git patches, SHA-256 manifests, Python 3.11/3.12, pytest, React/JavaScript, Node test runner, Playwright Chromium.

## Global Constraints

- Never run checkout, reset, clean, build, install, formatter, or dependency commands in the dirty worktree until the preservation package passes restore verification.
- Never delete or detach the registered worktree during this plan.
- Preserve user-authored untracked files and distinguish them from generated static assets.
- Start every portable implementation from current `main`; do not merge `feature/living-economy-map`.
- Treat current `main` as the compatibility baseline and require a test-backed reason for every port.
- Engine state and structured projections remain authoritative; model-authored numbers are untrusted narrative.
- Historical runs and pre-activation ticks must replay unchanged.

---

## File structure

- Create outside repository: `/home/ali/.codex/worktree-snapshots/agent-economy/living-economy-map-20260805/` — restorable patch, untracked archive, metadata, and hashes.
- Create: `docs/reconciliation/2026-08-05-dirty-worktree-inventory.md` — every path/hunk disposition and port mapping.
- Verify/Modify: `run.py` — resume hydration and forward-only activation boundaries.
- Verify/Modify: `agents/prompts.py` — grounded facts and entrepreneurship opportunities.
- Verify/Modify: `agents/memory.py` — bounded reserved-belief updates.
- Verify/Modify: `agents/runtime.py` — public reasoning sanitization.
- Create if portable: `agents/numeric_grounding.py` — pure numeric-claim extraction and sanitization.
- Verify/Modify: `world/newsroom.py` — public article numeric grounding.
- Verify/Modify: `reports/generate.py` — public report narrative grounding.
- Verify/Modify: `server/replay.py` — replay projection redaction.
- Verify/Modify: `dashboard/src/api.js` — unit-aware public formatting helpers.
- Verify/Modify: `dashboard/src/components/AgentsPanel.jsx`
- Verify/Modify: `dashboard/src/components/InformationPanels.jsx`
- Verify/Modify: `dashboard/src/components/MacroOverview.jsx`
- Verify/Modify: `dashboard/src/components/ReplayModal.jsx`
- Verify/Modify: `dashboard/src/components/RunHeader.jsx`
- Verify/Modify: `dashboard/src/components/WorldPanels.jsx`
- Test: `tests/test_compatibility_guards.py`
- Test: `tests/test_native_entrepreneurship.py`
- Test: `tests/test_research_validity.py`
- Test: `tests/test_information_completion.py`
- Test: `tests/test_report_narrative.py`
- Test: `dashboard/tests/*.test.js`
- Test: `dashboard/tests/e2e/world-os-privacy.spec.ts`

### Task 1: Create and verify the immutable preservation package

**Files:**
- Create outside repository: snapshot directory and contents.
- Verify only: `/home/ali/Documents/myprojects/agent-economy/.worktrees/living-economy-map/`

**Interfaces:**
- Consumes: dirty worktree branch tip, tracked diff, staged diff, and untracked files.
- Produces: a checksum-addressed package that restores the exact dirty state onto the recorded tip.

- [ ] **Step 1: Confirm the exact target and refuse aliases**

Run:

```bash
git worktree list --porcelain
git -C /home/ali/Documents/myprojects/agent-economy/.worktrees/living-economy-map rev-parse --show-toplevel
git -C /home/ali/Documents/myprojects/agent-economy/.worktrees/living-economy-map status --porcelain=v1 -z
```

Expected: the resolved top level exactly matches the registered path and the dirty inventory is captured. Do not use `~`, `$HOME`, a glob, or a recursive cleanup target.

- [ ] **Step 2: Create the fixed snapshot directory**

Run:

```bash
mkdir -p /home/ali/.codex/worktree-snapshots/agent-economy/living-economy-map-20260805/untracked
```

Expected: only that explicit directory is created.

- [ ] **Step 3: Capture repository metadata and binary patches**

Run:

```bash
git -C /home/ali/Documents/myprojects/agent-economy/.worktrees/living-economy-map rev-parse HEAD
git -C /home/ali/Documents/myprojects/agent-economy/.worktrees/living-economy-map merge-base HEAD main
git -C /home/ali/Documents/myprojects/agent-economy/.worktrees/living-economy-map diff --binary --output=/home/ali/.codex/worktree-snapshots/agent-economy/living-economy-map-20260805/tracked.patch
git -C /home/ali/Documents/myprojects/agent-economy/.worktrees/living-economy-map diff --cached --binary --output=/home/ali/.codex/worktree-snapshots/agent-economy/living-economy-map-20260805/staged.patch
```

Use `apply_patch` to create `metadata.md` containing the literal commit IDs, UTC timestamp, worktree path, branch name, and full porcelain status.

- [ ] **Step 4: Copy each untracked file byte-for-byte**

The current inventory contains:

```text
agents/numeric_grounding.py
server/static/assets/MacroOverview-EGrWjdWA.js
server/static/assets/index-C-RDqS0J.js
```

Copy those exact relative paths under the snapshot's `untracked/` directory with parents preserved. Re-run porcelain status first; if additional untracked paths appear, add each explicitly rather than using a broad archive glob.

- [ ] **Step 5: Secret-scan and hash the package**

Run the repository's maintained secret scanner against the patch files and copied untracked files. Then calculate SHA-256 for every package file and use `apply_patch` to create `SHA256SUMS` with the literal digest/path pairs in sorted order.

Expected: zero secret findings or an explicit stop for owner review; every file has one digest.

- [ ] **Step 6: Rehearse restoration in a temporary worktree**

Create a temporary worktree at the recorded branch tip, apply `tracked.patch`, apply `staged.patch` to the index, copy the three untracked files, and compare:

```bash
git diff --binary
git diff --cached --binary
sha256sum agents/numeric_grounding.py server/static/assets/MacroOverview-EGrWjdWA.js server/static/assets/index-C-RDqS0J.js
```

Expected: patches and hashes match the package exactly. Remove only the explicitly created temporary worktree after verification; retain the snapshot package.

### Task 2: Build the complete path-and-hunk disposition matrix

**Files:**
- Create: `docs/reconciliation/2026-08-05-dirty-worktree-inventory.md`

**Interfaces:**
- Consumes: verified snapshot, dirty worktree, current `main`, relevant current tests/commits.
- Produces: one evidence-backed disposition for every tracked and untracked path.

- [ ] **Step 1: Generate comparison evidence without changing either tree**

Run:

```bash
git -C /home/ali/Documents/myprojects/agent-economy/.worktrees/living-economy-map diff --stat
git -C /home/ali/Documents/myprojects/agent-economy/.worktrees/living-economy-map diff --numstat
git log main --oneline -- run.py agents/prompts.py tests/test_native_entrepreneurship.py
git diff --no-index -- /mnt/data/projects/agent-economy/run.py /home/ali/Documents/myprojects/agent-economy/.worktrees/living-economy-map/run.py
```

Repeat the no-index comparison for every dirty path. A nonzero `git diff --no-index` exit is expected when content differs.

- [ ] **Step 2: Create the matrix with fixed dispositions**

Use columns:

```markdown
| Dirty path | Hunk/contract | Current-main evidence | Disposition | Destination task | Verification |
|---|---|---|---|---|---|
```

Allowed dispositions are `equivalent`, `superseded`, `portable`, `needs-design`, and `generated`. Every row must cite a current function/test/commit or explain the incompatibility.

- [ ] **Step 3: Prove resume hydration is already equivalent or identify a gap**

Compare dirty `_hydrate_resumed_world` with current `run.py` and current tests:

```bash
.venv/bin/python -m pytest tests/test_compatibility_guards.py -q
```

Expected current evidence includes terminal report hydration and stale-running normalization. Mark the dirty hunks `equivalent` unless a focused failing test demonstrates a unique contract.

- [ ] **Step 4: Separate generated assets from authored sources**

Map each old/new `server/static/assets` file to the source build that produced it. Generated files receive `generated`; they may be rebuilt only after an accepted source port.

- [ ] **Step 5: Commit the inventory**

Run:

```bash
git add docs/reconciliation/2026-08-05-dirty-worktree-inventory.md
git diff --cached --check
git commit -m "docs: classify dirty worktree changes"
```

### Task 3: Close resume-hydration classification with regression evidence

**Files:**
- Verify/Modify: `run.py`
- Verify/Modify: `tests/test_compatibility_guards.py`
- Modify: `docs/reconciliation/2026-08-05-dirty-worktree-inventory.md`

**Interfaces:**
- Consumes: Task 2 comparison.
- Produces: explicit `equivalent` closure or a minimal current-main fix.

- [ ] **Step 1: Add a regression only for any unique dirty behavior**

The required contract is:

```python
assert resumed.status == "paused"          # stale process-local running marker
assert resumed.store.get_meta()["status"] == "paused"
assert resumed.last_report_path == str(expected_report)  # terminal persisted run
```

If current tests already assert all three at the correct phase boundaries, do not duplicate them.

- [ ] **Step 2: Run focused tests before editing implementation**

Run:

```bash
.venv/bin/python -m pytest tests/test_compatibility_guards.py tests/test_report_narrative.py -q
```

Expected: pass means the dirty hunk is equivalent; failure from a new unique regression authorizes the minimal fix.

- [ ] **Step 3: Implement only a demonstrated gap**

Preserve current semantics/schema checks, PRNG restoration order, stored config, active tick, and next phase. Never revive a process-local task after restart.

- [ ] **Step 4: Update inventory and commit**

If no code changes, commit only the inventory closure. If code changes, stage the focused test and `run.py` with it. Commit message:

```bash
git commit -m "fix: preserve resumed run lifecycle state"
```

### Task 4: Reconcile forward-only entrepreneurship activation

**Files:**
- Verify/Modify: `run.py`
- Verify/Modify: `agents/prompts.py`
- Verify/Modify: `agents/participant.py`
- Verify/Modify: `engine/actions.py`
- Verify/Modify: `runs/base.yaml`
- Verify/Modify: `runs/native-entrepreneurship.yaml`
- Modify: `tests/test_native_entrepreneurship.py`
- Modify: `tests/test_compatibility_guards.py`

**Interfaces:**
- Consumes: current entrepreneurship opportunity/action contract and dirty activation behavior.
- Produces: `activate_entrepreneurship_for_run(store) -> dict` as the forward-only activation interface.

- [ ] **Step 1: Add activation-boundary tests**

Write tests that assert:

```python
settings = activate_entrepreneurship_for_run(store)
assert settings["enabled"] is True
assert settings["activation_tick"] == next_untouched_tick
assert activate_entrepreneurship_for_run(store) == settings
```

Also assert running/replay/fork use is rejected, pre-boundary contexts contain no new opportunity, stored pre-feature formations replay, formation capacity is bounded, IP cannot precede completed financing, merger terms are engine-derived, and closure cannot deadlock on stale markers.

- [ ] **Step 2: Run focused tests and classify actual gaps**

Run:

```bash
.venv/bin/python -m pytest tests/test_native_entrepreneurship.py tests/test_semantics11_cognition.py tests/test_semantics12_civic_city.py tests/test_compatibility_guards.py -q
```

Expected: the new activation-boundary assertions fail before the helper is implemented; all unrelated existing assertions retain their prior result.

- [ ] **Step 3: Implement activation at the next untouched decision boundary**

Add a paused-run-only helper that persists config before world construction, returns existing enabled settings idempotently, and leaves historical behavior unchanged before `activation_tick`. CLI flags must be mutually exclusive with replay/fork and must not modify the caller-supplied profile file.

- [ ] **Step 4: Keep all terms engine-owned**

Prompts expose one bounded executable action. `ActionExecutor` rejects missing, mutated, stale, over-capacity, underfunded, premature-IP, or model-priced M&A actions atomically.

- [ ] **Step 5: Run compatibility/replay tests and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_native_entrepreneurship.py tests/test_semantics11_cognition.py tests/test_semantics12_civic_city.py tests/test_compatibility_guards.py tests/test_recorded_replay_golden.py -q
git diff --check
```

Commit only portable changes and update the inventory with the source hunk mapping.

### Task 5: Implement pure numeric-claim grounding

**Files:**
- Create: `agents/numeric_grounding.py`
- Modify: `agents/memory.py`
- Modify: `agents/prompts.py`
- Modify: `agents/runtime.py`
- Modify: `run.py`
- Modify: `tests/test_research_validity.py`
- Modify: `tests/test_compatibility_guards.py`

**Interfaces:**
- Produces: `model_grounding_active(config, tick)`, `numeric_claims(text)`, `narrative_numbers_are_grounded(text, sources)`, and `sanitize_model_numeric_narrative(text, *, grounding_enabled, fallback)`.
- Consumes: persisted `beliefs.model_grounding_from_tick` and bounded structured facts.

- [ ] **Step 1: Write failing pure-function tests**

Add:

```python
from agents.numeric_grounding import (
    narrative_numbers_are_grounded,
    numeric_claims,
    sanitize_model_numeric_narrative,
)


def test_numeric_claims_canonicalize_money_percent_and_commas():
    assert numeric_claims("Revenue was $3,000.00, up 7.50% from -2") == {
        "$3000", "7.5%", "-2",
    }


def test_public_narrative_rejects_derived_arithmetic():
    assert narrative_numbers_are_grounded("Output rose 75%", {"output": 30, "baseline": 20}) is False
    assert sanitize_model_numeric_narrative(
        "Output rose 75%",
        grounding_enabled=True,
        fallback="Current engine facts are authoritative.",
    ) == "Current engine facts are authoritative."
```

- [ ] **Step 2: Run focused tests and verify the module is absent**

Run:

```bash
.venv/bin/python -m pytest tests/test_research_validity.py -q
```

- [ ] **Step 3: Implement strict deterministic parsing**

Use `Decimal`, reject booleans as numerics, canonicalize signs/currency/percent, recursively collect supplied source numerics, and never execute model text. Preserve raw governed responses outside public sanitization.

- [ ] **Step 4: Add forward-only activation**

Implement `activate_numeric_grounding_for_run(store)` for paused runs. Persist `model_grounding_from_tick` at the next untouched decision phase and `model_max_reserved_step` as a nonnegative finite value. Repeated calls return the stored boundary.

- [ ] **Step 5: Bound reserved model belief updates**

After activation, model updates to trust, sentiment, and inflation require an existing supplied baseline and cannot move more than the configured step. Scripted engine updates and pre-boundary replay remain unchanged. Persist a rejection event without promoting the rejected value.

- [ ] **Step 6: Ground prompts and public reasoning**

Label current structured facts authoritative and memories historical. Allow public model text only when it contains no numbers or every numeric token occurs in the bounded source. Do not allow derived ratios even if derivable from source numbers.

- [ ] **Step 7: Run focused and compatibility tests and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_research_validity.py tests/test_compatibility_guards.py tests/test_memory_ranking.py tests/test_recorded_replay_golden.py -q
git add agents/numeric_grounding.py agents/memory.py agents/prompts.py agents/runtime.py run.py tests/test_research_validity.py tests/test_compatibility_guards.py
git diff --cached --check
git commit -m "feat: ground public model numeric claims"
```

### Task 6: Apply numeric grounding to news, reports, replay, and dashboard presentation

**Files:**
- Modify: `world/newsroom.py`
- Modify: `reports/generate.py`
- Modify: `server/replay.py`
- Modify: `dashboard/src/api.js`
- Modify: `dashboard/src/components/AgentsPanel.jsx`
- Modify: `dashboard/src/components/InformationPanels.jsx`
- Modify: `dashboard/src/components/MacroOverview.jsx`
- Modify: `dashboard/src/components/ReplayModal.jsx`
- Modify: `dashboard/src/components/RunHeader.jsx`
- Modify: `dashboard/src/components/WorldPanels.jsx`
- Modify: `tests/test_information_completion.py`
- Modify: `tests/test_report_narrative.py`
- Modify: `dashboard/tests/ui.test.js`
- Modify: `dashboard/tests/e2e/world-os-privacy.spec.ts`

**Interfaces:**
- Consumes: Task 5 numeric-grounding functions and activation boundary.
- Produces: `numeric_claims_redacted` public telemetry and unit-preserving `formatBeliefValue(key, value)`.

- [ ] **Step 1: Add failing newsroom/report/replay tests**

Assert an unsupported `987654321%` model claim is replaced in public news/report/replay, the raw governed LLM record remains, provenance reason is `ungrounded_numeric_claim`, and pre-activation content retains historical behavior.

- [ ] **Step 2: Add failing frontend formatting tests**

Use exact expectations:

```javascript
assert.equal(formatBeliefValue("trust:bank:1", 0.702131), "0.7021 (70.21%)");
assert.equal(formatBeliefValue("checking_balance_cents", 300000), "$3,000.00");
```

Assert historical memory and raw model output panels display warnings, while measured macro values retain existing units and precision.

- [ ] **Step 3: Run focused tests and observe failures**

Run:

```bash
.venv/bin/python -m pytest tests/test_information_completion.py tests/test_report_narrative.py -q
(cd dashboard && npm test)
```

- [ ] **Step 4: Sanitize public narrative at projection boundaries**

News, report, and replay use the same pure sanitizer after activation. Persist `numeric_claims_redacted: true` and reason telemetry without leaking the rejected text into public fields. Keep raw audited provider I/O governed by existing privacy policy.

- [ ] **Step 5: Add unit-aware frontend helpers and warnings**

Format known cents, rates, ratios, counts, and percentages by key; unknown values remain escaped plain text. Add explicit copy that memories may be stale and raw model numerics are unverified. Never store content in browser persistence.

- [ ] **Step 6: Run privacy and browser gates**

Run:

```bash
.venv/bin/python -m pytest tests/test_information_completion.py tests/test_report_narrative.py tests/test_research_validity.py -q
(
  cd dashboard
  npm test
  npm run typecheck
  npm run test:e2e -- --project=chromium tests/e2e/world-os-privacy.spec.ts
  npm run build
)
```

Expected: all pass and canaries remain absent from DOM, URL, storage, console, and public downloads.

- [ ] **Step 7: Commit public grounding**

Rebuild deterministic static output, stage accepted source/tests plus any resulting `server/static` diff, and commit:

```bash
git commit -m "fix: keep public numeric narratives grounded"
```

### Task 7: Account for every dirty hunk and retain the worktree safely

**Files:**
- Modify: `docs/reconciliation/2026-08-05-dirty-worktree-inventory.md`
- Verify: snapshot package and original dirty worktree.

**Interfaces:**
- Consumes: Tasks 1–6 and all original dirty paths.
- Produces: complete disposition proof; no deletion.

- [ ] **Step 1: Recount original paths against the inventory**

Every tracked and untracked path from the snapshot must have one final disposition and, for portable work, destination commit/test evidence. Counts must match exactly.

- [ ] **Step 2: Compare accepted ports with snapshot hunks**

Use patch IDs, function-level diffs, and tests to prove which behavior landed. Document intentional rewrites rather than claiming byte identity.

- [ ] **Step 3: Run the complete maintained gates**

Run all eight Python shards, dashboard unit/e2e/typecheck/licenses/audit/build, documentation tests, compatibility/replay tests, secret scan, and `git diff --check`.

- [ ] **Step 4: Re-verify preservation package and original worktree**

Run `sha256sum --check` on the package manifest and compare the original worktree's branch tip and porcelain status to Task 1. If it changed, explain and snapshot the new state before proceeding.

- [ ] **Step 5: Commit the final disposition record**

Run:

```bash
git add docs/reconciliation/2026-08-05-dirty-worktree-inventory.md
git diff --cached --check
git commit -m "docs: close dirty worktree salvage inventory"
```

- [ ] **Step 6: Stop before cleanup**

Report that salvage is complete, list retained snapshot/worktree locations, and request separate approval before any worktree removal, branch deletion, or generated-asset cleanup.

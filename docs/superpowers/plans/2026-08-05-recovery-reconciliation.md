# Supply and Workforce Recovery Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the unique recovery economics, lifecycle safety, checkpoint retention, and acceptance receipt work from `codex/reconcile-release` onto current `main` and prove it with a terminal source run plus exact replay.

**Architecture:** Preserve the original branch and historical database, then port behavior into a clean worktree in four reviewed layers. Keep domain math pure in `world/recovery.py`, make runtime integrations semantics-gated, split receipt orchestration from evidence/checkpoint validators, and require immutable source/replay receipts before merge.

**Tech Stack:** Python 3.11/3.12, SQLite, pytest, YAML run profiles, deterministic replay, Markdown/JSON receipts.

## Global Constraints

- Invoke `superpowers:using-git-worktrees` before creating the reconciliation worktree.
- Never rebase, reset, clean, or modify `codex/reconcile-release` or its registered worktree in place.
- Audit `820e5bf35e.db` read-only; never resume or write-open it to create post-change eligibility.
- Preserve semantics/version guards and exact replay for stored historical runs.
- Never delete a checkpoint body without atomically preserving catalog/manifest consistency.
- Intermediate health, `quick_check`, or zero sampled backlog is diagnostic only; acceptance requires the complete receipt and exact replay.
- Live-provider work is outside this plan; the recovery profile must remain provider-free.

---

## File structure

- Create: `docs/reconciliation/2026-08-05-recovery-port-ledger.md` — commit/path/conflict/disposition record.
- Create: `world/recovery.py` — pure recovery configuration, viability, price, wage, and capacity rules.
- Modify: `agents/prompts.py` — bounded completed-tick demand and vacancy context.
- Modify: `agents/policies.py` — recovery founder actions derived from qualified context.
- Modify: `agents/runtime.py` — recovery activation and safe action routing.
- Modify: `engine/actions.py` — action validation and stale recovery marker rejection.
- Modify: `engine/labor.py` — actual-wage/pay-interval hiring consistency.
- Modify: `world/loop.py` — recovery phase scheduling and terminal lifecycle handling.
- Modify: `run.py` — activation and `--supply-recovery-report` CLI.
- Create: `reports/supply_recovery.py` — public evaluator, receipt writer, and Markdown renderer.
- Create: `reports/supply_recovery_checks.py` — horizon, economics, backlog, insolvency, and ledger evidence.
- Create: `reports/supply_recovery_checkpoints.py` — catalog, manifest, SQLite, and retention evidence.
- Create: `runs/acceptance/supply-recovery.yaml` — provider-free qualifying profile.
- Create: `tests/test_supply_recovery.py` — pure economics and runtime context tests.
- Create: `tests/test_supply_recovery_report.py` — receipt mutation and CLI tests.
- Create: `tests/test_checkpoint_retention.py` — bounded retention and catalog/file atomicity tests.
- Modify: `tests/test_labor_ipo.py` — actual wage, offer, and merger lifecycle regressions.
- Modify: `tests/test_prd_completion.py` — current-main activation and integration regressions.

### Task 1: Preserve source evidence and build the port ledger

**Files:**
- Create: `docs/reconciliation/2026-08-05-recovery-port-ledger.md`

**Interfaces:**
- Consumes: current `main`, immutable `codex/reconcile-release`, historical `820e5bf35e.db`.
- Produces: `codex/reconcile-recovery-20260805`, a 26-commit disposition table, and a ten-area conflict ledger.

- [ ] **Step 1: Create a clean reconciliation worktree**

Run after the required worktree skill:

```bash
git fetch --prune origin
git worktree add .worktrees/reconcile-recovery-20260805 -b codex/reconcile-recovery-20260805 main
git -C .worktrees/reconcile-recovery-20260805 status --short --branch
```

Expected: clean branch at current `main`; the original recovery worktree remains registered and unchanged.

- [ ] **Step 2: Capture branch and conflict evidence**

Run:

```bash
git rev-list --left-right --count main...codex/reconcile-release
git log --reverse --format='%H|%s' main..codex/reconcile-release
git diff --stat main...codex/reconcile-release
git merge-tree "$(git merge-base main codex/reconcile-release)" main codex/reconcile-release
```

Expected: 26 branch-only commits are accounted for; overlapping paths and synthetic conflict markers are retained in the ledger.

- [ ] **Step 3: Audit the historical candidate immutably**

Run from the original recovery worktree without opening SQLite read-write:

```bash
sha256sum data/runs/820e5bf35e.db
.venv/bin/python -c "import sqlite3; p='file:data/runs/820e5bf35e.db?mode=ro&immutable=1'; c=sqlite3.connect(p, uri=True); print(c.execute('PRAGMA quick_check').fetchone()[0]); print(c.execute('SELECT run_id,tick,active_tick,next_phase,status FROM run_meta').fetchone())"
find data/runs -maxdepth 1 -name '820e5bf35e.db-*' -print
```

Expected: hash, integrity, phase/status, and sidecar inventory are recorded. Do not alter the file even if the run is resumable.

- [ ] **Step 4: Write the ledger with one row per commit**

Use these dispositions only:

```text
already-on-main | port-unchanged | port-synthesized | superseded | diagnostic-only
```

For each `port-synthesized` row, name the current-main function, branch function, deciding invariant, and required regression test. Include separate sections for recovery economics, lifecycle, checkpoints, receipt/reporting, and the historical candidate.

- [ ] **Step 5: Commit the ledger**

Run:

```bash
git add docs/reconciliation/2026-08-05-recovery-port-ledger.md
git diff --cached --check
git commit -m "docs: inventory recovery reconciliation"
```

### Task 2: Establish the pure recovery economics contract

**Files:**
- Create: `world/recovery.py`
- Create: `tests/test_supply_recovery.py`

**Interfaces:**
- Consumes: `config["firms"]["supply_recovery"]` and completed sales/stockout facts.
- Produces: `RecoveryAssessment`, `recovery_settings(config)`, `validate_recovery_settings(config)`, `assess_recovery(...)`, and `minimum_viable_price_cents(...)`.

- [ ] **Step 1: Write failing domain tests**

Add tests with the exact public interface:

```python
from world.recovery import assess_recovery, minimum_viable_price_cents


def test_recovery_rejects_wage_above_period_margin():
    result = assess_recovery(
        enabled=True,
        price_cents=1_000,
        input_cost_cents=300,
        output_per_worker=2,
        pay_interval_ticks=2,
        offered_wage_cents=1_401,
        incumbent_payroll_cents=0,
        cash_cents=50_000,
        fulfilled_units=20,
        stockout_units=0,
        current_headcount=1,
        open_vacancies=0,
        settings={"policy_version": 1, "headcount_cap": 10},
    )
    assert result.hire_allowed is False
    assert result.reason == "wage_exceeds_period_margin"


def test_minimum_viable_price_rounds_up_exactly():
    assert minimum_viable_price_cents(
        input_cost_cents=301,
        output_per_worker=3,
        pay_interval_ticks=2,
        wage_cents=1_000,
    ) == 968
```

- [ ] **Step 2: Run the tests and verify the module is missing**

Run:

```bash
.venv/bin/python -m pytest tests/test_supply_recovery.py -q
```

Expected: collection fails because `world.recovery` does not exist on current `main`.

- [ ] **Step 3: Implement typed settings and assessment**

Implement:

```python
@dataclass(frozen=True)
class RecoveryAssessment:
    enabled: bool
    hire_allowed: bool
    reason: str
    maximum_wage_cents: int
    target_headcount: int
    minimum_price_cents: int


def recovery_settings(config: Mapping[str, Any]) -> dict[str, int | bool | str]: ...
def validate_recovery_settings(config: Mapping[str, Any]) -> dict[str, int | bool | str]: ...
def assess_recovery(*, enabled: bool, price_cents: int, input_cost_cents: int,
                    output_per_worker: int, pay_interval_ticks: int,
                    offered_wage_cents: int, incumbent_payroll_cents: int,
                    cash_cents: int, fulfilled_units: int, stockout_units: int,
                    current_headcount: int, open_vacancies: int,
                    settings: Mapping[str, Any]) -> RecoveryAssessment: ...
def minimum_viable_price_cents(*, input_cost_cents: int,
                               output_per_worker: int,
                               pay_interval_ticks: int,
                               wage_cents: int) -> int: ...
```

Reject booleans where strict integers are required, unknown keys, unsupported policy versions, negative ticks, nonpositive observation windows, and invalid demand buffers. Use integer arithmetic and ceiling division; do not use binary floating point for money.

- [ ] **Step 4: Add the branch's boundary matrix**

Port focused cases for feature-off legacy behavior, one hire per period, incumbent payroll reservation, zero sales, stockout demand, headcount caps, observation windows, and normalized profile metadata. Keep each expected reason explicit.

- [ ] **Step 5: Run and commit the pure contract**

Run:

```bash
.venv/bin/python -m pytest tests/test_supply_recovery.py -q
git add world/recovery.py tests/test_supply_recovery.py
git diff --cached --check
git commit -m "feat: define sustainable recovery economics"
```

Expected: focused tests pass without touching runtime files.

### Task 3: Integrate completed-tick demand, vacancy, wage, and price behavior

**Files:**
- Modify: `agents/prompts.py`
- Modify: `agents/policies.py`
- Modify: `agents/runtime.py`
- Modify: `engine/actions.py`
- Modify: `engine/labor.py`
- Modify: `run.py`
- Modify: `tests/test_supply_recovery.py`
- Modify: `tests/test_prd_completion.py`
- Modify: `tests/test_workforce_recovery_bugs.py`

**Interfaces:**
- Consumes: Task 2 settings/assessment and current `activate_supply_recovery_for_run` boundary.
- Produces: deterministic context fields and engine-validated recovery actions active only at or after the persisted activation tick.

- [ ] **Step 1: Add failing context tests**

Add tests proving the context:

```python
def test_recovery_context_uses_only_completed_ticks(economy):
    context = build_recovery_context(economy, firm_id=1, tick=12)
    assert context["sales_window_end_tick"] == 11
    assert context["fulfilled_units"] == 7
    assert context["stockout_units"] == 3
    assert context["open_vacancies"] == 1
```

Use fixtures with one same-tick sale and one non-stockout rejection and assert neither enters recovery demand.

- [ ] **Step 2: Verify the focused failures**

Run:

```bash
.venv/bin/python -m pytest tests/test_supply_recovery.py tests/test_workforce_recovery_bugs.py -q
```

Expected: new context/decision assertions fail on current behavior.

- [ ] **Step 3: Implement bounded context and policy decisions**

Expose only completed-tick fulfilled sales, explicit stockout rejections, current vacancies, actual incumbent pay intervals, cash, inputs, output-per-worker, and configuration metadata. Policies may choose only among engine-qualified actions:

```python
{
    "action": "post_job",
    "occupation": qualified_occupation,
    "wage_cents": assessment.maximum_wage_cents,
    "slots": 1,
}
```

Do not let prompts derive demand units, wage ceilings, or price floors.

- [ ] **Step 4: Enforce actual wage and price constraints in the engine**

At execution, recompute viability using current state. Reject duplicate vacancies, stale applications/offers, insufficient cash, foreign-currency mismatches, and wages above actual period margin. A counteroffer must be rechecked at its final wage.

- [ ] **Step 5: Preserve forward-only activation and legacy replay**

Extend existing activation tests so pre-boundary ticks and stored runs without the settings retain their old paths. Repeated activation must return the persisted settings without moving the boundary.

- [ ] **Step 6: Run focused and compatibility tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_supply_recovery.py tests/test_prd_completion.py tests/test_workforce_recovery_bugs.py tests/test_compatibility_guards.py tests/test_recorded_replay_golden.py -q
```

Expected: all pass.

- [ ] **Step 7: Commit runtime economics**

Run:

```bash
git add agents/prompts.py agents/policies.py agents/runtime.py engine/actions.py engine/labor.py run.py tests/test_supply_recovery.py tests/test_prd_completion.py tests/test_workforce_recovery_bugs.py
git diff --cached --check
git commit -m "fix: converge supply recovery with viable economics"
```

### Task 4: Reconcile terminal firm and acquirer lifecycle evidence

**Files:**
- Modify: `engine/actions.py`
- Modify: `world/loop.py`
- Modify: `tests/test_labor_ipo.py`
- Modify: `tests/test_supply_recovery_report.py`

**Interfaces:**
- Consumes: authoritative firm status plus ordered bankruptcy/acquisition events.
- Produces: unambiguous producer and acquirer lifecycle markers bounded by the completed receipt horizon.

- [ ] **Step 1: Add failing lifecycle timing tests**

Cover these exact orderings:

```text
bankruptcy before same-tick merger -> acquirer invalid
merger before same-tick bankruptcy -> acquirer operating at close
acquisition before close -> acquirer invalid
acquisition after close -> acquirer valid at close
self-acquisition -> invalid
active firm with any unresolved bankruptcy marker -> invalid
```

Assert event IDs as well as ticks so same-tick ordering is deterministic.

- [ ] **Step 2: Run focused tests and observe failures**

Run:

```bash
.venv/bin/python -m pytest tests/test_labor_ipo.py tests/test_supply_recovery_report.py -q
```

Expected: new marker/timing tests fail.

- [ ] **Step 3: Implement authoritative event-order checks**

Use `(tick, event_id)` ordering and strict integer identity parsing. Persist enough acquisition/bankruptcy evidence to validate the producer and acquirer without guessing from the final status. Reject contradictory payload and subject identities.

- [ ] **Step 4: Run and commit lifecycle safety**

Run:

```bash
.venv/bin/python -m pytest tests/test_labor_ipo.py tests/test_supply_recovery_report.py -q
git add engine/actions.py world/loop.py tests/test_labor_ipo.py tests/test_supply_recovery_report.py
git diff --cached --check
git commit -m "fix: preserve recovery lifecycle evidence"
```

### Task 5: Implement bounded recovery checkpoint retention

**Files:**
- Modify: `engine/store.py`
- Modify: `world/loop.py`
- Create: `tests/test_checkpoint_retention.py`
- Create: `reports/supply_recovery_checkpoints.py`

**Interfaces:**
- Consumes: current checkpoint manifest/catalog APIs and configured recovery retention count.
- Produces: atomic catalog/file retention and `checkpoint_evidence(store, db_path, completed_tick)`.

- [ ] **Step 1: Add failure-injection tests**

Write tests for:

```python
def test_recovery_retention_never_leaves_catalog_file_mismatch(tmp_path): ...
def test_recovery_retention_keeps_terminal_and_required_boundary_checkpoints(tmp_path): ...
def test_checkpoint_evidence_rejects_manifest_hash_mismatch(tmp_path): ...
def test_checkpoint_evidence_rejects_sqlite_foreign_key_failure(tmp_path): ...
```

Simulate unlink failure and transaction failure separately. Assert either the old pair or new pair remains valid; never a half-pruned state.

- [ ] **Step 2: Run tests and verify failures**

Run:

```bash
.venv/bin/python -m pytest tests/test_checkpoint_retention.py -q
```

- [ ] **Step 3: Implement retention transaction ordering**

Select exact catalog rows first, validate resolved paths remain inside the configured checkpoint directory, retain terminal and governed boundary checkpoints, then update the catalog and files through a recoverable sequence. Never use a run-wide wildcard.

- [ ] **Step 4: Implement checkpoint evidence**

The validator must check catalog tick, manifest schema/version, database hash, manifest hash, immutable `quick_check`, `foreign_key_check`, sidecars, and required retention boundaries. Return structured pass/fail evidence; never repair files.

- [ ] **Step 5: Run and commit checkpoint safety**

Run:

```bash
.venv/bin/python -m pytest tests/test_checkpoint_retention.py -q
git add engine/store.py world/loop.py reports/supply_recovery_checkpoints.py tests/test_checkpoint_retention.py
git diff --cached --check
git commit -m "fix: retain recovery checkpoints atomically"
```

### Task 6: Build the fail-closed recovery receipt and CLI

**Files:**
- Create: `reports/supply_recovery_checks.py`
- Create: `reports/supply_recovery.py`
- Modify: `run.py`
- Create: `runs/acceptance/supply-recovery.yaml`
- Create: `tests/test_supply_recovery_report.py`

**Interfaces:**
- Consumes: Tasks 2–5, persisted run database, checkpoint directory.
- Produces: `resolve_supply_recovery_db`, `evaluate_supply_recovery`, `evaluate_supply_recovery_db`, `write_supply_recovery_receipt`, and `render_supply_recovery_markdown`.

- [ ] **Step 1: Add receipt-schema and CLI failure tests**

Assert this public structure:

```python
receipt = evaluate_supply_recovery_db(db_path)
assert receipt["schema"] == "agent-economy.supply-recovery-receipt.v1"
assert set(receipt["checks"]) == {
    "profile", "horizon", "purchases", "unemployment", "unit_economics",
    "producer_lifecycle", "labor_backlog", "ledger", "sqlite", "checkpoints",
}
assert receipt["passed"] is all(item["passed"] for item in receipt["checks"].values())
```

Add CLI tests proving no file is written without `--output`, JSON and Markdown are written together with `--output`, a failed receipt returns nonzero, and all run modifiers are rejected with `--supply-recovery-report`.

- [ ] **Step 2: Run tests and verify missing interfaces**

Run:

```bash
.venv/bin/python -m pytest tests/test_supply_recovery_report.py -q
```

Expected: import/CLI failures.

- [ ] **Step 3: Implement strict evidence checks**

In `reports/supply_recovery_checks.py`, require strict persisted integers, completed or headless-paused terminal boundary, exact profile settings, bounded purchase rejection and unemployment windows, viable unit economics, terminal producer/acquirer evidence, zero labor backlog, balanced ledger, and SQLite integrity. Preserve invalid raw evidence in sanitized form; never coerce fractional ticks or unknown statuses.

- [ ] **Step 4: Implement receipt orchestration and deterministic rendering**

In `reports/supply_recovery.py`, keep evaluation read-only, order checks canonically, hash the source database and output artifacts, write JSON atomically, and render Markdown entirely from the canonical receipt. Use DB-relative logical checkpoint paths so receipts do not leak absolute host paths.

- [ ] **Step 5: Add the CLI boundary**

Add:

```text
--supply-recovery-report RUN_ID_OR_DB
--output PATH
```

Make it mutually exclusive with run, resume, replay, fork, acceptance, and Oracle modifiers. Exit `0` only for a passing receipt.

- [ ] **Step 6: Add the provider-free profile**

Persist explicit recovery settings, horizon, checkpoint cadence/retention, target headcount, and acceptance thresholds in `runs/acceptance/supply-recovery.yaml`. Assert the profile routes no purpose to a live provider.

- [ ] **Step 7: Run mutation coverage and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_supply_recovery_report.py tests/test_supply_recovery.py tests/test_checkpoint_retention.py -q
git add reports/supply_recovery.py reports/supply_recovery_checks.py reports/supply_recovery_checkpoints.py run.py runs/acceptance/supply-recovery.yaml tests/test_supply_recovery_report.py
git diff --cached --check
git commit -m "feat: add supply recovery acceptance receipt"
```

### Task 7: Produce a qualifying source run and exact replay

**Files:**
- Create: ignored run database/checkpoints under `data/`.
- Create: ignored JSON/Markdown receipt under `reports/out/`.
- Modify: `docs/reconciliation/2026-08-05-recovery-port-ledger.md` with hashes/results only.

**Interfaces:**
- Consumes: reconciled head and provider-free recovery profile.
- Produces: terminal source receipt, integrity audit, exact replay receipt, and final merge evidence.

- [ ] **Step 1: Prove profile readiness without starting a run**

Run:

```bash
.venv/bin/python run.py --config runs/acceptance/supply-recovery.yaml --preflight
```

Expected: configuration and provider readiness pass with zero live routes and zero spend.

- [ ] **Step 2: Run the full configured horizon**

Run:

```bash
set -o pipefail
.venv/bin/python run.py --config runs/acceptance/supply-recovery.yaml 2>&1 | tee reports/out/supply-recovery-run.log
```

Expected: terminal persisted status at the profile horizon. Do not stop after a healthy intermediate tick.

- [ ] **Step 3: Generate and verify the source receipt**

Parse the standard structured run-open line from the preserved terminal log into a task-specific variable, require it to be nonempty, and generate the receipt:

```bash
AE_RECOVERY_RUN_ID=$(sed -n 's/^\[agent-economy\] run \([^ ]*\) @ tick.*/\1/p' reports/out/supply-recovery-run.log | tail -1)
test -n "$AE_RECOVERY_RUN_ID"
.venv/bin/python run.py --supply-recovery-report "$AE_RECOVERY_RUN_ID" --output "reports/out/supply-recovery-$AE_RECOVERY_RUN_ID.json"
```

Cross-check the parsed value against the database filename and receipt `run_id`. Expected: exit `0`, JSON and Markdown exist, all checks pass, and their hashes are recorded.

- [ ] **Step 4: Audit source database and checkpoints independently**

Open the database immutable/read-only and run `quick_check`, `foreign_key_check`, sidecar inventory, ledger reconciliation, and catalog/manifest/file comparison. Expected: all agree with the receipt.

- [ ] **Step 5: Replay without network dispatch**

Unset live-provider credentials, run the standard replay verifier, preserve its output, and require its canonical pass fields:

```bash
set -o pipefail
env -u MINIMAX_API_KEY -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u KIMI_API_KEY .venv/bin/python run.py --replay "$AE_RECOVERY_RUN_ID" 2>&1 | tee reports/out/supply-recovery-replay.log
rg '"exact": true' reports/out/supply-recovery-replay.log
rg '"differences": \[\]' reports/out/supply-recovery-replay.log
```

Expected: replay reaches the same tick, consumes each recorded response once, dispatches no live request, reports identical logical hash/deterministic tables, and emits `differences: []`.

- [ ] **Step 6: Verify replay receipt and update the ledger**

Record source/replay IDs, commits, configuration digest, database hashes, receipt hashes, checkpoint counts, replay hash, and zero-difference result. Do not commit generated databases or secrets.

- [ ] **Step 7: Commit evidence pointers**

Run:

```bash
git add docs/reconciliation/2026-08-05-recovery-port-ledger.md
git diff --cached --check
git commit -m "docs: record supply recovery acceptance evidence"
```

### Task 8: Run the full merge gate and review the final diff

**Files:**
- Verify: every file changed by Tasks 1–7.

**Interfaces:**
- Consumes: complete reconciled implementation and qualifying evidence.
- Produces: merge-ready branch, not a public-release claim.

- [ ] **Step 1: Run all eight Python shards**

```bash
for AE_CI_SHARD_INDEX in 0 1 2 3 4 5 6 7; do
  .venv/bin/python -m pytest tests/ -q -p scripts.pytest_shard --ci-shard-index "$AE_CI_SHARD_INDEX" --ci-shard-count 8 || exit 1
done
```

Expected: all pass; environment skips are itemized.

- [ ] **Step 2: Run dashboard, documentation, dataset, and diff gates**

Run:

```bash
(cd dashboard && npm ci && npm test && npm run typecheck && npm run licenses:check && npm audit --audit-level=high && npm run test:e2e -- --project=chromium && npm run build)
.venv/bin/python -m pytest tests/test_documentation.py tests/test_dataset_verification.py -q
git diff --check main...HEAD
```

Expected: all pass.

- [ ] **Step 3: Compare every original recovery commit with the ledger**

Run `git range-diff`, `git cherry`, and path diffs. Expected: every one of the 26 source commits has a documented disposition and every ported invariant has a test.

- [ ] **Step 4: Request code review and address only verified findings**

Invoke the repository's review workflow. For each finding, reproduce it against current control flow, add a focused regression, fix, and rerun the relevant gate. A clean automated review is supporting evidence, not a replacement for tests.

- [ ] **Step 5: Final merge-readiness check**

Expected final state:

```text
tracked tree clean
original recovery branch/worktree unchanged
historical candidate hash unchanged
source receipt passed
SQLite/checkpoints passed
exact replay passed with no differences
full maintained gates passed
```

Only then open the reconciliation PR.

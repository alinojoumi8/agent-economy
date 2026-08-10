# 308-Agent Economic-Recovery Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task inline. Steps use checkbox (`- [ ]`) syntax for tracking; this thread does not authorize sub-agent delegation.

**Goal:** Reproduce the 308-agent scale configuration from tracked profiles, prove economic recovery through deterministic persisted receipts, pass a 120-tick A/B and 1,000-tick provider-free acceptance, then validate capped MiniMax and DeepSeek canaries in real Chrome.

**Architecture:** Keep configuration, execution-time measurement, and immutable offline evaluation separate. Maintained YAML profiles define identity; `scripts/run_scale_validation.py` creates source/replay runtime receipts; `reports/scale_economic_health.py` validates source, replay, runtime, economic, resource, checkpoint, and communication evidence without mutating runs. Each of the five stages is reviewed and merged independently before the next starts.

**Tech Stack:** Python 3.11/3.12, asyncio, SQLite, PyYAML, psutil, pytest, existing Agent Economy world/ledger/checkpoint/replay code, GitHub Actions, Google Chrome, and the existing MiniMax/DeepSeek OpenAI-compatible adapters.

## Global Constraints

- Follow `AGENTS.md`: all economic mutation remains in `engine/` or deterministic `world/` mechanics, all monetary effects use the ledger, and historical source runs are never rewritten during replay.
- Keep seed 42 and semantics 7 for unchanged acceptance mechanics. The repository has generated source/replay lifecycle fixtures for semantics 1 and 2, a preserved live golden fixture at semantics 5, and the maintained semantics 7 acceptance profile; it does not have dedicated exact-replay fixtures for semantics 3, 4, or 6. Every final verification runs the semantics 1/2 lifecycle fixtures, the semantics 5 recorded golden, and a fresh semantics 7 source/replay. A fix that changes persisted output must introduce a new persisted `engine_semantics_version`, separate profiles/receipts, and an additional exact source/replay case for that new version. It must preserve all older behavior, keep the all-supported-version resume guard green, and never rewrite a stored source run.
- Keep population size 270, 308 total agents, 272 citizen-kind rows, 36 staff rows, 100 core agents, 208 periphery agents, and regional counts 184/69/55.
- Keep 25 coverage-first conversation pairs per tick and three persisted turn messages per conversation; system, tool, and provider-private rows do not count as messages.
- Provider-free work uses only `scripted/scripted` and records USD 0 spend.
- MiniMax uses only `minimax/MiniMax-M3` under a USD 0.50 cap; DeepSeek uses only `deepseek/deepseek-v4-flash` under a USD 0.20 cap.
- Never commit SQLite run/checkpoint bodies, credentials, Authorization headers, cookies, private reasoning, raw private provider bodies, or unrestricted environment dumps.
- Diagnostic evidence cannot satisfy the 1,000-tick gate; integrity/replay cannot substitute for economic-health gates.
- Stage N+1 starts only after stage N is merged, post-merge CI is green, local `main` equals `origin/main`, and `gh pr list --state open` returns an empty list.
- GitHub issue 52 remains the tracking issue until all five stages pass.
- Execute every stage inline in the primary session through `superpowers:executing-plans`.

---

## Stage 1: Permanent 270-Sampled-Citizen Profiles and Regressions

### Task 1.1: Add the provider-free profile

**Files:**
- Create: `runs/scale-270-rehearsal.yaml`
- Reference: `runs/scale-170-rehearsal.yaml`

**Interfaces:**
- Consumes: `run_config.load_config(path: Path) -> dict` and the existing regional Genesis allocator.
- Produces: a maintained provider-free config with exact 308-agent identity for later diagnostic and formal profiles.

- [ ] **Step 1: Add the profile regression before the profile**

Create `tests/test_scale_270_profiles.py` with constants and a failing existence/configuration test:

```python
ROOT = Path(__file__).resolve().parents[1]
REHEARSAL = ROOT / "runs" / "scale-270-rehearsal.yaml"

def test_scale_270_rehearsal_is_exact():
    config = load_config(REHEARSAL)
    assert config["seed"] == 42
    assert config["engine_semantics_version"] == 7
    assert config["population"] == {
        "baseline_citizens_core": False,
        "size": 270,
    }
    assert config["living_world"]["core_agents"] == 100
    assert [r["population"] for r in config["living_world"]["regions"]] == [182, 70, 56]
    assert [r["currency"] for r in config["living_world"]["regions"]] == ["NSD", "IVC", "SCD"]
    assert config["banks"]["count"] == 3
    assert config["checkpoint_every"] == 7
    assert config["checkpoint_keep_last"] == 4
    assert config["speed_delay_s"] == 0.0
    assert config["budget"]["conversation_pairs"] == 25
    assert config["conversations"]["coverage_first"] is True
    assert config["llm"]["default_route"] == {
        "provider": "scripted", "model": "scripted",
    }
    assert config["llm"]["routes"] == {}
    assert config["resource_guard"] == {
        "enabled": True,
        "sample_interval_s": 2,
        "max_cpu_percent": 95,
        "max_memory_percent": 85,
        "min_available_memory_gb": 8,
        "max_swap_percent": 80,
        "consecutive_breaches": 3,
    }
```

- [ ] **Step 2: Verify the test fails for the missing profile**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_scale_270_profiles.py::test_scale_270_rehearsal_is_exact
```

Expected: failure because `runs/scale-270-rehearsal.yaml` does not exist.

- [ ] **Step 3: Create the exact profile**

Copy the maintained semantics/provider/resource structure from
`runs/scale-170-rehearsal.yaml`, changing only:

```yaml
population:
  baseline_citizens_core: false
  size: 270

living_world:
  core_agents: 100
  regions:
    - {key: northstar, name: Northstar Federation, currency: NSD, population: 182, specialization: [technology, services, finance], x: 0.25, y: 0.35, legal_ruleset: northstar-us-inspired-1.0, rate_ppm: 1000000}
    - {key: ironvale, name: Ironvale Union, currency: IVC, population: 70, specialization: [manufacturing, energy], x: 0.72, y: 0.28, legal_ruleset: external-lite-1.0, rate_ppm: 750000}
    - {key: suncoast, name: Suncoast Republic, currency: SCD, population: 56, specialization: [agriculture, logistics, tourism], x: 0.55, y: 0.78, legal_ruleset: external-lite-1.0, rate_ppm: 1200000}

budget:
  conversation_pairs: 25
```

Retain checkpoint interval 7, retention 4, three regional banks, semantics 7,
coverage-first conversations, scripted-only routing, and the existing resource
guard.

- [ ] **Step 4: Verify configuration passes**

Run the focused test from Step 2 and expect one pass.

### Task 1.2: Add exact population, coverage, and replay tests

**Files:**
- Modify: `tests/test_scale_270_profiles.py`
- Modify: `run.py`

**Interfaces:**
- Consumes: `run.open_run`, `run.replay_headless`, `world.replay_verify.verify_replay`.
- Extends: `run.open_run(..., data_dir=replay_dir, replay_source_dir=source_dir)` so replay output and its immutable source never share a write root.
- Produces: regressions for exact Genesis identity, ledger reconciliation, seven-tick communication coverage, and source-artifact-immutable one-tick replay.

- [ ] **Step 1: Add a failing exact-Genesis test**

```python
def test_scale_270_rehearsal_builds_exact_population(tmp_path):
    store, world, _ = open_run(load_config(REHEARSAL), None, None, data_dir=tmp_path)
    try:
        assert store.scalar("SELECT COUNT(*) FROM agents") == 308
        assert store.scalar("SELECT COUNT(*) FROM agents WHERE kind='citizen'") == 272
        assert store.scalar("SELECT COUNT(*) FROM agents WHERE kind='staff'") == 36
        assert store.scalar("SELECT COUNT(*) FROM agents WHERE population_tier='core'") == 100
        assert store.scalar("SELECT COUNT(*) FROM agents WHERE population_tier='periphery'") == 208
        assert _region_counts(store) == {"northstar": 184, "ironvale": 69, "suncoast": 55}
        ok, diagnostic = world.economy.ledger.reconcile()
        assert ok, diagnostic
    finally:
        world.close()
```

- [ ] **Step 2: Add the seven-tick coverage regression**

Sample 25 pairs for ticks 1 through 7 using
`world.conversations._sample_pairs`, collect all participant IDs, and assert the
set equals all 308 living agents. Do not dispatch model calls in this unit test.

- [ ] **Step 3: Add source-artifact-immutable exact replay regression**

Run one scripted tick under a dedicated `source_dir` and close it. Build a
canonical source artifact-set manifest containing the main database, every
source-owned checkpoint body and manifest, and explicit absent entries for
`-wal`, `-shm`, and rollback-journal sidecars. Hash every present artifact and
make the complete source tree read-only. Extend `open_run` with a keyword-only
`replay_source_dir` used only to locate the read-only source while `data_dir`
remains the distinct replay-output root; reject equal, nested, or otherwise
overlapping resolved roots before creating a replay database. Open the source
only through the existing read-only `Store`/SQLite boundary, create the replay
under `replay_dir`, and call `replay_headless` on that world. The regression
must intercept and reject every attempted writable open under `source_dir`,
assert `exact is True`, `differences == []`, and matching source/replay ticks and
aggregate hashes, then rebuild and compare the complete source artifact-set
manifest byte-for-byte. Restore test-only filesystem permissions during
teardown without modifying an artifact body.

- [ ] **Step 4: Run all provider-free profile tests**

```bash
.venv/bin/python -m pytest -q tests/test_scale_270_profiles.py -k 'rehearsal or population or coverage or replay'
```

Expected: all selected tests pass with no ledger or replay difference.

### Task 1.3: Add exact paid canary profiles

**Files:**
- Create: `runs/scale-270-minimax-live.yaml`
- Create: `runs/scale-270-deepseek-live.yaml`
- Modify: `tests/test_scale_270_profiles.py`

**Interfaces:**
- Consumes: the exact provider definitions in the scale-170 live profiles and `llm.readiness.validate_llm_config`.
- Produces: fail-closed two-provider canary configs for Stage 5.

- [ ] **Step 1: Add failing parameterized route/cap tests**

```python
LIVE_CASES = [
    (MINIMAX, "MINIMAX_API_KEY", "minimax", "MiniMax-M3", 3, 0.50),
    (DEEPSEEK, "DEEPSEEK_API_KEY", "deepseek", "deepseek-v4-flash", 6, 0.20),
]

@pytest.mark.parametrize("profile,key,provider,model,concurrency,cap", LIVE_CASES)
def test_scale_270_live_profiles_are_exact(monkeypatch, profile, key, provider, model, concurrency, cap):
    monkeypatch.setenv(key, "test-key-only")
    config = load_config(profile)
    report = validate_llm_config(config, raise_on_error=False)
    assert report["ready"], report["errors"]
    assert config["seed"] == 42
    assert config["population"]["size"] == 270
    assert config["llm"]["route_contract"] == {"provider": provider, "model": model}
    assert config["llm"]["concurrency"] == concurrency
    assert config["budget"]["cap_usd"] == cap
    assert config["budget"]["oracle_reserve_usd"] == 0.0
    assert config["budget"]["report_reserve_usd"] == 0.0
    expected_route = {"provider": provider, "model": model}
    assert config["llm"]["routes"] == {
        purpose: expected_route for purpose in EXPECTED_LIVE_PURPOSES
    }
    reference = load_config(SCALE_170_BY_PROVIDER[provider])
    assert config["llm"]["providers"][provider] == reference["llm"]["providers"][provider]
    assert config["llm"]["pricing"] == reference["llm"]["pricing"]
```

`EXPECTED_LIVE_PURPOSES` is the exact sorted purpose tuple declared by the
maintained scale-170 profiles. The provider-block comparison covers base URL,
credential environment name, timeouts, healthcheck path, request defaults,
pricing, concurrency, token field, cache mode, and documented-model/fallback
settings without duplicating them in the test.

Add a second parameterized test that removes the required key and asserts
readiness is false with at least one error.

- [ ] **Step 2: Verify both tests fail for missing profiles**

Run the two test functions directly and expect missing-profile failures.

- [ ] **Step 3: Create both canary profiles**

Extend `scale-270-rehearsal.yaml`. Preserve the exact provider blocks, routes,
request defaults, pricing, and concurrency from the corresponding scale-170
profiles. Set the MiniMax cap to 0.50 and DeepSeek cap to 0.20; set both reserves
to 0.0.

- [ ] **Step 4: Run Stage 1 verification**

```bash
.venv/bin/python -m pytest -q tests/test_scale_270_profiles.py tests/test_scale_170_profiles.py
.venv/bin/python -m pytest -q tests/test_documentation.py tests/test_external_agent_gateway.py tests/test_research_export.py tests/test_prd_completion.py tests/test_recorded_replay_golden.py
scripts/secret_scan.sh staged
git diff --check
```

Expected: every command passes and the staged scan reports no leak.

### Task 1.4: Review, publish, merge, and close the PR boundary

- [ ] **Step 1: Commit Stage 1 only**

```bash
git add runs/scale-270-rehearsal.yaml runs/scale-270-minimax-live.yaml runs/scale-270-deepseek-live.yaml tests/test_scale_270_profiles.py
git commit -m "feat: add permanent 308-agent scale profiles"
```

- [ ] **Step 2: Review and publish**

Review `git diff origin/main...HEAD`, run CodeRabbit/reviewer checks, fix valid
findings with focused regressions, push a normal branch, and open a PR linked to
issue 52 with `Stage 1` in the title.

- [ ] **Step 3: Merge only after required PR checks pass**

Use squash merge and delete the remote branch. Do not start Stage 2 while the PR
or any required check is open.

- [ ] **Step 4: Verify the post-merge boundary**

Fast-forward local `main`, verify the three profiles and test file are present,
wait for the matching `main` CI run to pass, verify `origin/main...main` is
`0 0`, and assert `gh pr list --state open --json number` returns `[]`. Check
Stage 1 in issue 52.

---

## Stage 2: Runtime Harness and Persisted Economic-Health Receipt

### Task 2.1: Port the runtime harness under tests

**Files:**
- Create: `scripts/run_scale_validation.py`
- Create: `tests/test_scale_validation.py`
- Reference: `/tmp/agent-economy-scale270-validation.py`

**Interfaces:**
- Consumes: `load_config`, `validate_llm_config`, `provider_preflight`, `open_run`, `replay_headless`, `verify_replay`.
- Produces: `run_validation(profile: Path, ticks: int, label: str, output_dir: Path, data_dir: Path, approve_live: bool) -> dict[str, object]` and a CLI that writes one sanitized runtime receipt.

- [ ] **Step 1: Write failing unit tests for input and sanitization boundaries**

Cover rejection of non-positive ticks, rejection of a live profile without
`--approve-live-inference`, rejection of a profile outside `runs/`, exact
profile-derived caps, an explicit `data_dir`, repository-relative artifact
identifiers, and recursive absence of credential values, Authorization headers,
cookies, private reasoning, raw private provider bodies, unrestricted
environment dumps, and embedded or encoded SQLite run/checkpoint bodies in
runtime, economic, aggregate, and browser receipt fixtures.

- [ ] **Step 2: Verify the tests fail because the module is missing**

```bash
.venv/bin/python -m pytest -q tests/test_scale_validation.py
```

- [ ] **Step 3: Port the temporary harness with repository-safe boundaries**

Use `ROOT = Path(__file__).resolve().parents[1]`; remove all scale overrides so
the loaded profile is authoritative; keep per-tick/checkpoint/RSS/DB metrics;
pass the explicit `data_dir` through source, replay, checkpoint, and manifest
operations; record and compare the complete source artifact-set manifest before
and after replay; make execution reusable through `run_validation`; write JSON
atomically; and emit a compact stdout summary containing receipt path, source
run ID, replay run ID, result, tick, calls, spend, and replay status.

- [ ] **Step 4: Add a one-tick provider-free integration test**

Run the permanent rehearsal with `data_dir=tmp_path / "runs"`, assert 308
agents, 25 conversations, 75 messages, scripted-only calls, zero spend, clean
integrity, at least one checkpoint, exact replay, and no absolute repository
path in the serialized receipt. Assert every generated database, checkpoint,
manifest, and receipt is beneath the isolated `tmp_path` root.

- [ ] **Step 5: Run harness tests**

Run `tests/test_scale_validation.py` and the permanent profile tests. Expect all
passes.

### Task 2.2: Add diagnostic and formal recovery profiles

**Files:**
- Create: `runs/acceptance/scale-270-baseline-120.yaml`
- Create: `runs/acceptance/scale-270-recovery-120.yaml`
- Create: `runs/acceptance/scale-270-recovery-1000.yaml`
- Modify: `tests/test_scale_270_profiles.py`

**Interfaces:**
- Consumes: `runs/scale-270-rehearsal.yaml` and exact settings from `runs/acceptance/supply-recovery.yaml`.
- Produces: persisted stage/horizon identity for the offline evaluator.

- [ ] **Step 1: Add failing inheritance and exact-contract tests**

Assert baseline is provider-free, requires 120 ticks, and has recovery disabled;
recovery-120 differs only by the exact recovery policy; recovery-1000 requires
1,000 ticks, checkpoint interval 100, retention 2, and the same recovery policy.

- [ ] **Step 2: Add the profiles**

Persist this contract in each profile:

```yaml
acceptance:
  scale_economic_health:
    schema_version: 1
    required_ticks: 120
    warmup_ticks: 60
    trailing_window_ticks: 60
    max_buy_goods_rejection_rate: 0.05
    max_unemployment_rebound: 0.10
    max_pending_applications: 20
    max_pending_job_offers: 20
    max_open_jobs: 20
    max_peak_rss_mb: 2048
    min_available_memory_gb: 8
    max_database_growth_bytes_per_tick: 8388608
    max_checkpoint_p95_seconds: 5.0
```

Set `required_ticks: 1000`, checkpoint interval 100, and retention 2 in the
formal profile. Copy the exact ten `supply_recovery` fields from the maintained
supply-recovery acceptance profile into both recovery profiles.

- [ ] **Step 3: Run profile tests**

Expect exact inheritance, identity, and provider-free tests to pass.

### Task 2.3: Implement the immutable economic-health evaluator

**Files:**
- Create: `reports/scale_economic_health.py`
- Create: `tests/test_scale_economic_health.py`
- Reference: `reports/supply_recovery.py`
- Reference: `world/replay_verify.py`

**Interfaces:**
- Consumes: source DB path, replay DB path, runtime receipt path.
- Produces: `evaluate_scale_economic_health`, `write_scale_economic_health_receipt`, `render_scale_economic_health_markdown`, `evaluate_scale_ab`, `write_scale_ab_receipt`, and `python -m reports.scale_economic_health`.

- [ ] **Step 1: Build a deterministic healthy 120-tick fixture**

Create source/replay fixture databases with exact run/profile identity, 308-agent
counts, 120 metrics rows, resolved buy-goods proposals at no more than 5%
rejection, final-window production/inventory/labor evidence, reconciled ledger,
valid checkpoints/manifests, and an exact replay proof. Create a matching
runtime receipt with resource values below every cap.

- [ ] **Step 2: Write the failing all-green contract test**

```python
receipt = evaluate_scale_economic_health(source, replay, runtime)
assert receipt["schema"] == "agent-economy-scale-economic-health-v1"
assert receipt["passed"] is True
assert all(receipt["checks"].values())
assert receipt == evaluate_scale_economic_health(source, replay, runtime)
```

- [ ] **Step 3: Write fail-closed mutation tests**

Parameterize mutations for wrong profile/config hash, wrong population/tiering or
regions, tick 119, active phase, unresolved proposal, rejection rate over 5%,
unemployment rebound over 10 points, worsening final mean unemployment, missing
production, persistent zero inventory, excessive labor backlog, invalid wage or
currency, insolvency, ledger imbalance, SQLite sidecar, checkpoint/hash mismatch,
replay difference, source mutation, provider spend in a scripted arm, peak RSS
over 2 GiB, available memory below 8 GiB, DB growth over 8 MiB/tick, checkpoint
p95 over 5 seconds, and secret-canary keys in runtime evidence.

- [ ] **Step 4: Verify tests fail before implementation**

Run the new test module and expect import/contract failures.

- [ ] **Step 5: Implement immutable loading and evidence sections**

Open databases with `mode=ro&immutable=1` and `PRAGMA query_only=ON`; reject
sidecars. Implement focused helpers for identity, population, proposals,
unemployment, production/inventory, labor, integrity, checkpoints, replay,
communications, providers/spend, and resources. Return JSON-compatible evidence
for every check, including an explicit error when evidence is missing.

- [ ] **Step 6: Implement deterministic atomic JSON/Markdown output and CLI**

The CLI requires `--source`, `--replay`, `--runtime-receipt`, and `--output`.
It writes both extensions atomically and uses this exact exit contract after
output exists: `0` for a passing receipt; `10` for an expected economic-only
failure on a 120-tick diagnostic profile when every operational/integrity/replay
check passed; `5` for operational, artifact, integrity, replay, formal-horizon,
or unexpected failures; and `2` for CLI misuse. Receipt JSON carries the same
`outcome` value (`passed`, `diagnostic_economic_failure`, or `failed`) so callers
never infer meaning from prose.

- [ ] **Step 7: Implement and test the A/B aggregate boundary**

`evaluate_scale_ab(baseline: Mapping[str, object], recovery: Mapping[str,
object]) -> dict[str, object]` verifies both receipt schemas and operational
checks. It compares canonical effective runtime configs after resolving
inheritance and removes only non-semantic identity fields (`profile_path`,
`label`, receipt/output paths, and the diagnostic recovery-arm name). It permits
differences only in the exact `supply_recovery` policy block; every other seed,
semantics, population, tiering, region, conversation, route, budget, checkpoint,
resource, and inherited acceptance value must match. It emits canonical
per-window deltas. `write_scale_ab_receipt` writes atomic JSON/Markdown and
passes only when both arms are operationally valid and the recovery arm passes
every economic check; baseline economic failures remain visible diagnostics.

- [ ] **Step 8: Run focused and integration tests**

```bash
.venv/bin/python -m pytest -q tests/test_scale_economic_health.py tests/test_scale_validation.py tests/test_scale_270_profiles.py tests/test_supply_recovery_report.py
```

Expected: every test passes and existing supply-recovery receipts remain
unchanged.

### Task 2.4: Document, verify, review, and merge Stage 2

**Files:**
- Modify: `docs/development.md`
- Modify: `tests/test_documentation.py`

- [ ] **Step 1: Document exact provider-free, evaluator, and live-approval commands**

Document raw runtime output under ignored `reports/out/`, sanitized evidence
under `benchmarks/receipts/scale-270/`, local SQLite retention, and the rule that
live flags are invalid for provider-free profiles and mandatory for paid ones.

- [ ] **Step 2: Run Stage 2 verification**

Run the Stage 2 focused suite, the `AGENTS.md` smoke suite, documentation tests,
secret scan, and `git diff --check`.

- [ ] **Step 3: Commit, review, PR, CI, and merge**

Commit only Stage 2 files, review the complete diff and CodeRabbit findings,
open one Stage 2 PR linked to issue 52, merge only after required checks pass,
then repeat the post-merge `main`/CI/divergence/open-PR audit from Stage 1. Check
Stage 2 in issue 52.

---

## Stage 3: 120-Tick Provider-Free Baseline/Recovery A/B

### Task 3.1: Execute both exact arms

**Files:**
- Generate locally: `reports/out/scale-270/ab-120/`
- Create tracked sanitized evidence: `benchmarks/receipts/scale-270/ab-120/`

**Interfaces:**
- Consumes: Stage 2 profiles, harness, and evaluator.
- Produces: two runtime receipts, two economic receipts, two Markdown renderings, and one aggregate comparison bound to source/replay/config hashes.

- [ ] **Step 1: Preflight host and repository state**

Verify clean `main`, `0 0` divergence, zero open PRs, at least 20 GiB free disk,
at least 8 GiB available memory, no conflicting run process, and no credential
output. Record exact commit/tree in the local run log.

- [ ] **Step 2: Run the 120-tick baseline**

```bash
.venv/bin/python scripts/run_scale_validation.py \
  --profile runs/acceptance/scale-270-baseline-120.yaml \
  --ticks 120 \
  --label baseline-120 \
  --output-dir reports/out/scale-270/ab-120
```

Capture source/replay IDs from the compact stdout JSON. Do not treat an economic
failure as a harness failure when operational/replay checks pass.

- [ ] **Step 3: Evaluate baseline immutably**

Invoke `python -m reports.scale_economic_health` with the emitted source DB,
replay DB, and runtime receipt; write sanitized output to
`benchmarks/receipts/scale-270/ab-120/baseline`. Accept only exit `0` or the
explicit diagnostic exit `10`; require the JSON outcome to match the exit. Any
exit `2` or `5` stops the A/B as an operational failure.

- [ ] **Step 4: Run and evaluate the recovery arm**

Repeat Steps 2-3 with
`runs/acceptance/scale-270-recovery-120.yaml`, label `recovery-120`, and output
stem `benchmarks/receipts/scale-270/ab-120/recovery`.

### Task 3.2: Publish the causal comparison

- [ ] **Step 1: Verify both sources and replays again**

Re-run immutable quick checks, foreign keys, source hashes, config hashes,
checkpoint manifests, and replay comparisons. Confirm both arms share seed,
population, regions, core/periphery, conversations, and scripted route; confirm
only recovery configuration differs.

- [ ] **Step 2: Generate canonical aggregate JSON/Markdown**

Invoke the Stage 2 `write_scale_ab_receipt` boundary. The aggregate reports
purchase acceptance/rejection, unemployment windows, production, inventory,
labor, insolvency, resources, checkpoint p95, DB growth, and replay results for
both arms. It marks baseline economic failure as diagnostic and requires
operational integrity for both.

- [ ] **Step 3: Run evidence and secret verification**

Run focused receipt tests, JSON parsing, artifact hash verification, secret
scan across the new evidence, documentation tests, and `git diff --check`.

- [ ] **Step 4: Commit, review, PR, CI, and merge Stage 3 evidence**

Commit only sanitized receipts/renderings and any tested aggregate helper. Open
one Stage 3 PR, resolve review findings, merge after checks, then verify green
post-merge CI, `0 0` divergence, and zero open PRs. Check Stage 3 in issue 52.

---

## Stage 4: Enforce and Pass the 120-Tick Recovery Gate

### Task 4.1: Diagnose any failed recovery checks

**Files:**
- Inspect: `agents/policies.py`
- Inspect: `world/recovery.py`
- Inspect: `world/loop.py`
- Inspect: `engine/actions.py`
- Inspect: `world/metrics.py`
- Modify only the files whose persisted boundary reproduces a failed gate.
- Test: `tests/test_supply_recovery.py`
- Test: `tests/test_workforce_recovery_bugs.py`
- Test: `tests/test_scale_economic_health.py`

**Interfaces:**
- Consumes: failed recovery receipt and exact per-tick source rows.
- Produces: a reproduced root cause, regression, minimal semantics-safe fix, and fresh passing 120-tick source/replay receipt.

- [ ] **Step 1: Recompute every failed metric from authoritative rows**

For each failed check, compare `action_proposals`, `events`, `metrics`, firms,
employment/jobs/applications/offers, accounts/ledger, checkpoints, runtime
receipt, and source/replay proof at the same tick. Record the first causal tick
and the actors/firms/goods involved without modifying the source.

- [ ] **Step 2: Write the smallest failing regression at the reproduced boundary**

Add success and rejection cases plus ledger reconciliation and exact replay.
If the failure is configuration-only, add an inheritance regression proving the
missing recovery setting. Do not change thresholds.

- [ ] **Step 3: Implement the minimal governed fix**

Keep policy choice in `agents/` or deterministic `world/`; keep mutations in
`engine/`; route monetary effects through the ledger; use a new semantics guard
only if stored historical output would otherwise change.

- [ ] **Step 4: Run focused, compatibility, and replay tests**

Run the new regression, supply/workforce suites, generated semantics 1/2 replay
lifecycle fixtures, the recorded semantics 5 golden, a fresh semantics 7
source/replay, the all-supported-version resume guard, scale receipt/profile
suites, and the required smoke suite. Run an additional exact source/replay
case for a new semantics version only when this stage introduces one; dedicated
semantics 3/4/6 exact-replay fixtures do not currently exist and are not claimed.

- [ ] **Step 5: Run a fresh 120-tick recovery arm**

Never reuse a pre-fix source. Run the accepted recovery profile and evaluator
from Stage 3 against a fresh source/replay pair. Repeat Steps 1-5 until every
economic, integrity, resource, checkpoint, and replay check passes.

### Task 4.2: Publish passing recovery evidence and merge

- [ ] **Step 1: Preserve failed attempts as diagnostic evidence**

Keep local run bodies and sanitized failed receipts distinct. Never overwrite a
failed receipt with a passing identity.

- [ ] **Step 2: Add the final passing receipt and a deterministic delta report**

Publish the accepted source/replay/runtime hashes and compare it with the Stage
3 baseline and first recovery attempt. State every code/config change and gate.

- [ ] **Step 3: Run the complete Stage 4 verification**

Run focused economic suites, compatibility/replay tests, the repository smoke
suite, applicable full Python shards, documentation, secret scan, and diff
checks.

- [ ] **Step 4: Commit, review, PR, CI, and merge Stage 4**

Commit fixes, regressions, and sanitized final evidence only. Merge one reviewed
Stage 4 PR after all checks, then verify post-merge CI, `0 0` divergence, and
zero open PRs. Check Stage 4 in issue 52.

If the first recovery arm already passed, Stage 4 still publishes a separate
gate-closure receipt that promotes that immutable diagnostic identity to the
accepted 120-tick prerequisite; no kernel change is invented merely to create a
diff.

---

## Stage 5: 1,000-Tick Acceptance and Real Paid Chrome Canaries

### Task 5.1: Pass the formal provider-free recovery acceptance

**Files:**
- Generate locally: `reports/out/scale-270/formal-1000/`
- Create tracked evidence: `benchmarks/receipts/scale-270/formal-1000/`

- [ ] **Step 1: Preflight exact accepted commit and host capacity**

Verify clean/synchronized `main`, zero open PRs, no run process, at least 20 GiB
free disk, at least 8 GiB available memory, and the formal profile digest.

- [ ] **Step 2: Run exactly 1,000 scripted ticks**

```bash
.venv/bin/python scripts/run_scale_validation.py \
  --profile runs/acceptance/scale-270-recovery-1000.yaml \
  --ticks 1000 \
  --label recovery-1000 \
  --output-dir reports/out/scale-270/formal-1000
```

Do not shorten the horizon after a slow or healthy intermediate tick.

- [ ] **Step 3: Evaluate the formal source/replay/runtime triple**

Write canonical JSON/Markdown under
`benchmarks/receipts/scale-270/formal-1000/`. Require every check true. Re-run
source hash, immutable SQLite, ledger, checkpoint manifests, and replay proof
after report generation to prove the evaluator did not mutate either DB.

### Task 5.2: Implement the immutable completed-run observatory

**Files:**
- Modify: `server/replay.py`
- Create: `server/read_only_observatory.py`
- Create: `dashboard/src/components/ReadOnlyRunObservatory.jsx`
- Modify: `dashboard/src/App.jsx`
- Test: `tests/test_read_only_observatory.py`
- Test: `dashboard/tests/read-only-observatory.test.js`
- Test: `dashboard/tests/e2e/read-only-observatory.spec.ts`

**Interfaces:**
- Produces: `create_read_only_observatory_app(*, runs_dir, run_id, expected_manifest) -> FastAPI` and `python -m server.read_only_observatory --runs-dir ... --run-id ... --manifest ... --host 127.0.0.1 --port 8001`.
- Extends: `ReplayReader` with an explicit completed-source mode and persisted-only status/region, agent list/detail, conversation/message, and provider/model/spend projections; its existing active-run default remains WAL-aware.

- [ ] **Step 1: Add failing backend boundary and projection tests**

Build a completed source fixture with agents, regions, messages, and `llm_calls`.
Require the standalone app to expose the exact pinned run ID, completed tick,
status, expected source hash, 308-agent/regional counts, paginated agent
list/detail, persisted conversation threads, and aggregate provider/model/spend.
Assert every route method is only `GET`, `HEAD`, or `OPTIONS`; representative
run, shock, participant, fork, acceptance, and WebSocket mutation paths must be
absent or return 405. Assert `app.state` has no `World`, gateway, store writer,
or `RunController`.

- [ ] **Step 2: Implement immutable SQLite projections and the standalone app**

Add an explicit `ReplayReader(..., immutable_completed=True, run_id=...)` mode
that uses `mode=ro&immutable=1`, `PRAGMA query_only=ON`, one exact allowlisted
run ID, bounded pagination, and persisted/public fields only. Preserve the
existing default `ReplayReader()` behavior with `mode=ro` and no immutable flag
so the live application's replay routes continue to observe committed WAL rows.
Reject immutable-completed mode unless the source is closed and every sidecar is
absent. The standalone FastAPI app is the only caller that enables this mode;
it serves the production static bundle and only the read-only projections above.
It must not call `create_app`, instantiate a `World`/gateway/controller, install
external/operator routes, create a database, or accept a source outside
`runs_dir`. Startup fails on a missing/mismatched manifest, any WAL/SHM/rollback-
journal sidecar, a non-completed source, an occupied port, or a source path that
resolves through a symlink outside the pinned root. Recheck the complete
artifact manifest on shutdown.

- [ ] **Step 3: Add the dedicated read-only dashboard surface**

Route `/read-only-runs/:runId` to `ReadOnlyRunObservatory`. Render the pinned run
ID/hash/status, population and regions, agent directory/detail, conversation
threads/messages, and provider/model/spend using only the standalone GET APIs.
Render an explicit `Immutable completed run` badge and no buttons/forms for
step, pause, resume, shock, fork, join, participant submission, or provider
dispatch. Do not open a WebSocket or poll a mutating/live endpoint in this mode.

- [ ] **Step 4: Prove source immutability and browser usability**

Capture the canonical source artifact-set manifest before TestClient and
Playwright sessions and compare it byte-for-byte after shutdown, including
explicit absent sidecars. Intercept every SQLite/file open and fail on a
writable access mode under the source root. Add a separate WAL regression using
the default reader to prove a committed active-run row remains visible; assert
only `immutable_completed=True` adds the immutable URI flag. Unit-test empty/
paginated views, 404s for another run ID, route-method allowlisting,
sanitization, and spend rounding. In Playwright, cover directory/detail
navigation, conversations, provider/spend, immutable controls, desktop/narrow
layouts, and zero console, page, or failed-request errors.

- [ ] **Step 5: Run focused backend and dashboard verification**

Run the new Python tests, dashboard unit/type/build tests, and the dedicated
Playwright spec before any paid inference. The observatory contract must pass
against a completed scripted fixture before it is allowed to serve a canary.

### Task 5.3: Run capped MiniMax M3 canary and Chrome verification

**Files:**
- Generate locally: `reports/out/scale-270/minimax-canary/`
- Create tracked sanitized evidence: `benchmarks/receipts/scale-270/minimax-canary/`

- [ ] **Step 1: Secret-safe provider preflight**

Load `.env` without printing it, validate only MiniMax is routed, run the live
`/models` preflight, and confirm the profile cap is USD 0.50.

- [ ] **Step 2: Run exactly two live ticks**

```bash
.venv/bin/python scripts/run_scale_validation.py \
  --profile runs/scale-270-minimax-live.yaml \
  --ticks 2 \
  --label minimax-canary \
  --output-dir reports/out/scale-270/minimax-canary \
  --approve-live-inference
```

Require positive spend at or below cap, only `minimax/MiniMax-M3`, 50
conversations, 150 non-empty persisted turn messages, and exactly 100 distinct
paid-core participants. Query all 50 persisted `participant_ids` pairs and
assert each contains two distinct core IDs and no core ID repeats across pairs.
Require clean integrity/checkpoints and exact offline replay.

- [ ] **Step 3: Serve the exact completed source read-only and test Chrome**

Build the canonical closed source artifact-set manifest and verify port 8001 is
free, then start only the Stage 5.2 standalone process at `127.0.0.1:8001` with
the explicit source root, run ID, and manifest; do not attach a `World`,
`RunController`, participant writer, or mutation route. Verify the listening PID
and command are that exact process and that its status API returns the expected
run ID and source hash. Use installed Google Chrome to verify the UI displays
those identities plus status/header, 308-agent population and regions, agent
directory/detail, persisted conversation threads, provider/model and spend
surfaces, absent write controls, desktop and narrow viewport, console/page
errors, and failed requests. Capture screenshots and a sanitized browser JSON
receipt bound to commit, source run ID, tick, process identity, and the
pre-launch artifact-set manifest. Rebuild the manifest after shutdown and fail
the browser gate if the main DB, a checkpoint body/manifest, or an explicit
sidecar absence entry differs.

- [ ] **Step 4: Shut down and prove the server is down**

Terminate the exact server process, verify port 8001 is no longer listening,
and confirm the complete source artifact-set manifest is unchanged.

### Task 5.4: Run capped DeepSeek canary and Chrome verification

Repeat Task 5.3 sequentially with `runs/scale-270-deepseek-live.yaml`, only
`deepseek/deepseek-v4-flash`, cap USD 0.20, and a fresh source/replay/browser
identity. Do not start DeepSeek while MiniMax's server or run process remains.

### Task 5.5: Publish final evidence, merge, and close the goal

- [ ] **Step 1: Build a final aggregate receipt**

Include the Stage 3 baseline/recovery 120-tick A/B aggregate, the Stage 4
gate-closure receipt, formal provider-free, MiniMax, DeepSeek, and both browser
receipts. Bind every input by stage identity, commit, profile/config digest,
source/replay/runtime identity, and artifact hash. Require both Stage 3 arms to
have passed their operational contract, the accepted 120-tick recovery arm and
Stage 4 gate closure to pass every recovery/economic gate, the formal economic
gate, both route/cap gates, both communications gates, both browser gates, every
replay, and every integrity check.

- [ ] **Step 2: Run final verification**

Run scale/economic tests, supply recovery, the generated semantics 1/2 lifecycle
fixtures, recorded semantics 5 golden, a fresh semantics 7 source/replay, the
all-supported-version resume guard, and an exact new-version source/replay only
when a new persisted version was introduced, plus the required smoke suite,
dashboard unit/type/build/Playwright gates affected by the browser path,
documentation, dependency/secret scans, evidence hash verifier, a recursive
prohibited-artifact scan across every runtime/economic/aggregate/browser receipt,
and `git diff --check`.

- [ ] **Step 3: Commit, review, PR, CI, and merge final evidence**

Commit only sanitized receipts, screenshots, renderings, and tested fixes. Open
one Stage 5 PR linked to issue 52, resolve review findings, and merge only after
required checks pass.

- [ ] **Step 4: Perform the completion audit**

Fast-forward local `main`; verify post-merge CI green, `origin/main...main` is
`0 0`, no dirty tracked files, `gh pr list --state open` is empty, every issue
52 checkbox is checked, all referenced artifacts/hash paths exist, no DB/key is
tracked, and both server/provider processes are stopped. Close issue 52 only
after this audit passes.

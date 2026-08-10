# 308-Agent Economic-Recovery Acceptance Design

## Goal

Turn the successful short 308-agent mechanical scale experiment into a
versioned, fail-closed economic-recovery program. The program must prove that
the larger economy recovers supply and labor health before another population
increase or another long paid run, while preserving the already verified
MiniMax M3, DeepSeek V4 Flash, communications, checkpoint, and exact-replay
boundaries.

## Current boundary

`main` already contains permanent 170-sampled-citizen profiles that create 208
agents: 100 model-capable core agents and 108 deterministic periphery agents.
The local 270-sampled-citizen experiment used temporary overrides to create 308
agents: 100 core and 208 periphery. Its seven-tick provider-free rehearsal and
two-tick provider canaries passed population, communications, route, spend,
resource, checkpoint, ledger, SQLite, and 118-table exact-replay checks.

Those scale artifacts are intentionally ignored and are not reproducible from
tracked profiles. More importantly, the seven-tick source recorded only 55
accepted goods purchases against 1,432 rejected goods purchases, and its
unemployment metric remained 0.79296875. The earlier 208-agent 90-tick live
runs also ended with high unemployment and high purchase rejection. Mechanical
correctness is therefore proven at 308 agents, but economic health is not.

The repository also contains `supply-recovery-v1`, a provider-free 1,000-tick
acceptance profile, and a deterministic persisted evaluator. The scale profiles
do not currently enable that recovery policy. The next boundary is a controlled
same-seed scale comparison followed by a formal recovery acceptance.

## Approved delivery sequence

The work is split into five ordered stages. Stage N+1 cannot begin until stage N
is merged to `main`, post-merge CI is green, local `main` equals `origin/main`,
and GitHub reports zero open pull requests.

1. Commit permanent 270-sampled-citizen profiles and profile regressions.
2. Commit a deterministic persisted scale economic-health receipt and runtime
   harness.
3. Run and publish a 120-tick provider-free baseline/recovery A/B.
4. Fix any recovery failures and enforce every economic gate until the recovery
   arm passes.
5. Pass the formal 1,000-tick provider-free acceptance, then pass separately
   capped MiniMax M3 and DeepSeek V4 Flash canaries in real Chrome.

GitHub issue 52 is the tracking record for these stages. Each stage uses its
own branch and pull request. The tracking issue remains open across stages, but
no pull request may remain open between stages.

## Considered approaches

### 1. Versioned profiles, a dedicated scale receipt, and staged runs — selected

Add the 308-agent configuration as maintained YAML, port the proven temporary
measurement harness into the repository, and add a persisted scale evaluator
that composes the existing recovery contract with scale, resource, replay, and
communications evidence. Run a cheap 120-tick A/B before the 1,000-tick gate
and before either provider canary.

This keeps configuration, runtime measurement, and offline acceptance separate;
it also makes failed or partial evidence useful without allowing it to pass.

### 2. Generalize `reports/supply_recovery.py` in place

Parameterizing the existing 1,800-line evaluator could support both the legacy
recovery profile and the new scale lane. It would also risk changing a mature,
strict acceptance contract and would make the scale-specific population,
communications, resource, and replay-pair rules harder to review. Existing
supply-recovery behavior remains authoritative and is consumed rather than
weakened.

### 3. Keep using an external temporary validation script

This minimizes repository changes but leaves the exact population overrides,
measurement semantics, and receipt schema unreviewed and non-reproducible. It
cannot support a durable 1,000-tick or release-evidence claim.

## Maintained profiles

### Common 308-agent profile

`runs/scale-270-rehearsal.yaml` extends `runs/base.yaml` and pins:

- seed 42 and `engine_semantics_version: 7` for the unchanged acceptance
  mechanics; a recovery fix that changes persisted output must introduce and
  persist a new maintained semantics version instead of rewriting version 7;
- `population.size: 270` and `baseline_citizens_core: false`;
- three currency-matched regional banks;
- configured regional populations 182, 70, and 56;
- expected post-Genesis regional populations 184, 69, and 55;
- 308 living agents, including 272 `citizen` rows and 36 `staff` rows;
- 100 core agents and 208 deterministic periphery agents;
- 25 coverage-first conversation pairs per tick and three turns; each turn
  creates exactly one non-empty row in `messages`, while system prompts, tool
  calls, and provider-private reasoning are excluded from that table;
- checkpoint interval 7, retention 4, zero delay, and the existing resource
  guard;
- scripted/scripted as the only provider/model route.

The profile does not silently enable recovery. It is the common baseline used
to distinguish scale behavior from the effect of `supply-recovery-v1`.

### Paid canary profiles

`runs/scale-270-minimax-live.yaml` and
`runs/scale-270-deepseek-live.yaml` extend the common profile. They preserve the
existing exact route contracts, provider settings, pricing, and concurrency.
The MiniMax cap is USD 0.50 and the DeepSeek cap is USD 0.20. Oracle and report
reserves are zero so the hard cap is the actual all-purpose canary boundary.

The profiles are canary profiles, not long-run authorization. A run must still
receive an explicit tick horizon, and the maintained canary horizon is two
completed ticks.

### Diagnostic and formal recovery profiles

`runs/acceptance/scale-270-baseline-120.yaml` extends the common profile and
persists the diagnostic acceptance contract without enabling recovery.
`runs/acceptance/scale-270-recovery-120.yaml` extends the baseline diagnostic
profile and enables the exact `supply-recovery-v1` settings already maintained
by `runs/acceptance/supply-recovery.yaml`.

`runs/acceptance/scale-270-recovery-1000.yaml` extends the recovery diagnostic
profile, raises the required horizon to 1,000 ticks, uses checkpoint interval
100 and retention 2, and remains provider-free.

## Runtime harness

`scripts/run_scale_validation.py` owns execution-time evidence. It replaces the
temporary 608-line script and accepts only a maintained profile plus explicit
tick horizon, label, output directory, isolated run-store/checkpoint root, and
optional live-provider approval.

The harness:

1. loads `.env` through the repository's existing local secret boundary;
2. validates the complete LLM route contract before world creation;
3. performs live provider preflight only for a live profile;
4. runs to the exact requested tick and rejects a partial phase;
5. measures per-tick wall time, RSS, available memory, logical SQLite growth,
   and checkpoint duration;
6. checks population, communications, provider/model calls, spend governor,
   ledger, SQLite, foreign keys, and failure events;
7. closes the source and builds a canonical artifact-set manifest covering the
   main database, source-owned checkpoint bodies/manifests, and explicit absence
   of WAL, SHM, and rollback-journal sidecars;
8. creates an offline replay that dispatches no provider call, using a distinct
   replay-output directory and a non-overlapping, read-only source directory;
9. delegates comparison to `world.replay_verify.verify_replay`, which compares
   the sorted union of every non-excluded source/replay table and fails any
   missing or unequal table; the receipt records the schema version, compared
   table names/count, and SHA-256 of the verifier module rather than inventing a
   separate catalog version;
10. confirms the complete source artifact-set manifest did not change;
11. emits one sanitized JSON runtime receipt.

The harness never commits or deletes run/checkpoint databases. It never writes
credentials, Authorization headers, raw private provider bodies, private
reasoning, cookies, or an environment dump. Runtime receipts use repository-
relative profile and artifact identifiers; public evidence omits host-private
absolute paths.

## Persisted economic-health receipt

`reports/scale_economic_health.py` owns offline evaluation. Its public boundary
is:

```python
def evaluate_scale_economic_health(
    source_db: str | Path,
    replay_db: str | Path,
    runtime_receipt: str | Path,
) -> dict[str, object]:
    ...

def write_scale_economic_health_receipt(
    source_db: str | Path,
    replay_db: str | Path,
    runtime_receipt: str | Path,
    *,
    output: str | Path,
) -> dict[str, object]:
    ...
```

The evaluator opens both databases immutable and read-only, rejects WAL/SHM
sidecars, verifies schema compatibility, verifies the runtime receipt and
source/replay hashes, and derives every economic result from persisted rows.
Repeated evaluation of identical artifacts produces identical authoritative
JSON. Markdown is a deterministic rendering of that JSON.

The evaluator consumes the existing supply-recovery settings and thresholds;
it does not lower them for scale. It adds scale-specific checks for profile
identity, exact population/tiering/regions, communications, resources, database
growth, checkpoint timings, and source/replay identity.

## Economic and operational gates

### Horizon and identity

- Diagnostic arms: terminal at exactly 120 completed ticks with no active
  phase.
- Formal arm: terminal at exactly 1,000 completed ticks with no active phase.
- Population: exactly 308 alive agents, 272 citizen-kind, 36 staff, 100 core,
  208 periphery, and regional counts 184/69/55.
- The profile path, configuration digest, seed, semantics version, recovery
  policy version, and source commit must match the persisted/runtime evidence.

### Purchases, production, and inventory

- Warmup is 60 ticks and the rolling evaluation window is 60 ticks.
- Every completed post-warmup rolling window has at least one resolved
  `buy_goods` proposal, zero unresolved proposals, and rejection rate at or
  below 0.05.
- Every active goods firm has production evidence in the final 60 ticks.
- Final-window production units are at least final-window accepted sale units.
- No active goods firm remains at zero inventory for the entire final window.
- Recovery-managed unit economics and insolvency checks from the existing
  supply-recovery contract pass.

### Labor

- The unemployment rebound between adjacent 60-tick windows is at most 0.10.
- The final 60-tick mean unemployment is no greater than the first 60-tick
  mean.
- Pending applications, pending job offers, and open jobs are each at or below
  20 at the terminal tick.
- Every active employment uses the firm's currency and a positive persisted
  wage/pay interval.

### Integrity, replay, and resources

- Immutable SQLite `quick_check` is `ok`, foreign keys are clean, and every
  currency ledger reconciles.
- Required checkpoint catalog rows, files, manifests, hashes, and terminal
  tick agree.
- Replay reaches the exact source tick, uses no live provider, compares all
  deterministic tables with no differences, and leaves the source SHA-256
  unchanged.
- Peak process RSS is at most 2 GiB, minimum available host memory is at least
  8 GiB, logical database growth is at most 8 MiB per completed tick, and
  checkpoint p95 duration is at most 5 seconds.
- Provider-free arms persist zero paid spend. Paid arms persist positive spend
  at or below their hard cap, with no fallback provider/model.

## A/B design

Both 120-tick arms use seed 42, the same 308-agent population, 100/208 tiering,
regional allocation, conversations, checkpoint policy, and scripted route. The
only economic-policy difference is `supply-recovery-v1`.

The baseline is allowed to fail economic gates; its purpose is causal
comparison. Both arms must still complete their horizon and pass operational,
integrity, checkpoint, and exact-replay gates. The recovery arm must pass every
economic gate before stage 4 can close. If it fails, the failed receipt remains
diagnostic evidence and any behavior change requires a fresh source and replay.

The baseline evaluator may return the explicit
`diagnostic_economic_failure` outcome only when every operational, artifact,
integrity, and replay check passes and only economic checks fail. That outcome
uses exit code 10 so the orchestrator can continue to the recovery arm without
confusing the baseline diagnosis with success. CLI misuse is exit 2;
operational, unexpected, or formal failures are exit 5; a pass is exit 0.

The published A/B evidence contains canonical receipts, configuration hashes,
source/replay hashes, aggregate economic windows, resource slopes, and exact
sanitized commands. SQLite bodies and credentials remain local and ignored.

## Recovery-fix boundary

Failures are diagnosed at the persisted proposal/event/metric/ledger boundary.
Permitted fixes include scale-dependent inventory-aware demand, production,
staffing, capital, wage, offer, and recovery-policy mechanics. Monetary effects
must flow through the ledger. Behavior changes are guarded by the existing
semantics mechanism so historical behavior remains exact. The repository
currently has generated exact-replay lifecycle fixtures for semantics 1 and 2,
a recorded live golden at semantics 5, and a maintained semantics 7 acceptance
source/replay; it has no dedicated exact-replay fixtures for semantics 3, 4, or
6. Every final verification runs 1/2, 5, and 7 plus the all-supported-version
resume guard. A new semantics version is a new-run schema/config path only:
schema changes are additive columns or tables, changed behavior/output is gated
by persisted `engine_semantics_version`, and neither source databases nor
receipts are ever rewritten during replay. An additional exact source/replay
case is required only when a new persisted version is introduced, before that
profile is eligible.

Every fix begins with a failing regression and includes success, rejection,
reconciliation, and exact-replay coverage. Receipt thresholds are not weakened
to make a failed run pass.

## Formal acceptance and live canaries

After the 120-tick recovery arm passes, the same accepted code/configuration
runs for 1,000 provider-free ticks. The formal source and offline replay must
pass every receipt check. An intermediate healthy tick, a completed source
without its replay, or a receipt missing runtime evidence is not acceptance.

Only then are the two paid canaries run, sequentially:

- MiniMax: exactly `minimax/MiniMax-M3`, two completed ticks, cap USD 0.50.
- DeepSeek: exactly `deepseek/deepseek-v4-flash`, two completed ticks, cap
  USD 0.20.

Each canary must record 50 conversations and 150 non-empty `messages` rows: two
distinct paid-core participants per conversation and three persisted turn rows,
with system/tool/private rows excluded. Coverage-first scheduling must use each
of the 100 paid-core IDs exactly once across the 50 pairs, with no repeated core
ID. Each canary persists only its exact provider/model, stays under cap, passes
checkpoints/integrity/replay, and exposes the completed run through the real
application in installed Google Chrome.

Chrome verification serves the completed source through the existing
read-only `ReplayReader`/static observatory boundary with no `World` or mutating
controller attached. It builds and compares the complete source artifact-set
manifest before launch and after shutdown and fails if the main database,
checkpoint bodies/manifests, or sidecar-absence entries change. The browser gate covers page load, run header/status,
population and region views, agent directory/details, persisted
conversations/messages, provider and spend surfaces, unavailable write controls,
console errors, page errors, failed requests, desktop layout, and a narrow
viewport. Screenshots and a sanitized browser receipt are hash-bound to the
source run and exact commit.

## Failure handling

- A failed or partial run is retained as diagnostic evidence and never relabeled
  as passing.
- A provider preflight or canary failure stops that canary; it does not fall
  back to another provider and does not authorize a larger cap.
- A resource guard pause, cap pause, partial tick, replay divergence, hash
  mismatch, checkpoint inconsistency, integrity error, or secret scan failure
  fails closed.
- Reports never mutate source databases. A write-opened source loses evidence
  eligibility.
- No cleanup command removes unrelated runs, checkpoints, worktrees, or user
  artifacts.

## Verification and merge discipline

Each stage runs focused tests, the repository smoke suite required by
`AGENTS.md`, relevant full Python shards, documentation checks, secret scans,
and `git diff --check`. Provider and browser stages additionally run the exact
runtime/evidence commands.

Before every merge:

1. review the complete branch diff and runtime evidence;
2. run the applicable CodeRabbit/reviewer checks and resolve valid findings;
3. push a normal branch and open one pull request;
4. wait for required CI to pass;
5. merge without force;
6. fast-forward local `main` to `origin/main`;
7. verify the merge commit contains the expected files;
8. verify GitHub has zero open pull requests before starting the next stage.

## Acceptance evidence

The full objective is complete only when issue 52 has five checked stages; the
final aggregate binds the Stage 3 120-tick A/B aggregate and Stage 4 gate-closure
receipt by identities and hashes and confirms their operational and recovery
gates; the formal provider-free source/replay receipt passes; both paid canary
and browser receipts pass; every stage is merged into `main`; post-merge CI is
green; local and remote `main` match; and GitHub has no open pull request.

## Out of scope

- Adding another 100 citizens before the formal gate passes.
- A paid 90-day or 365-day campaign.
- Weakening the established 5% purchase-rejection or 10-percentage-point
  unemployment-rebound contracts.
- Public deployment, tagging, or unrelated external-connector release gates.
- Committing SQLite run/checkpoint bodies or secrets.

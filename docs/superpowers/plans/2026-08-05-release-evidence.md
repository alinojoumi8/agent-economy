# Release Evidence and Public Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fail-closed, offline-verifiable release-evidence package and execute each remaining external, hosted, live-provider, experiment, long-horizon, and final-audit gate under its own explicit authorization.

**Architecture:** Gate runners emit immutable content-addressed receipts. A repository-owned collector validates a versioned manifest against one exact candidate commit/tree and renders canonical JSON plus deterministic Markdown without network access. Execution scope and status stay independent so local, live-provider, and independent-external evidence cannot substitute for one another.

**Tech Stack:** Python 3.11/3.12, pytest, YAML/JSON, SHA-256, immutable SQLite inspection, Git, MiniMax-M3 through the existing OpenAI-compatible adapter, Playwright Chromium, npm, OAuth 2.0/OIDC, hosted REST/MCP clients.

## Global Constraints

- Implement and test the collector offline before any paid, hosted, external-client, deployment, or publication action.
- Never store API keys, bearer tokens, cookies, OAuth codes, refresh tokens, private messages, private reasoning, authorization headers, or unrestricted environment dumps in receipts.
- Store approved live credentials only in an ignored mode-600 file; commands may source it but must never print it.
- Bind every qualifying receipt to the exact release-candidate Git commit and tree. A dirty tree or later source change invalidates the aggregate.
- `execution_scope` is exactly `local`, `live_provider`, or `independent_external`; `status` is exactly `passed`, `failed`, `blocked`, or `not_run`.
- Local mocks, rehearsals, provider probes, partial runs, archived Oracle V1-V8 artifacts, and blocked receipts never satisfy a required gate.
- Preserve failed and partial evidence as append-only diagnostics. Never rewrite a failed receipt into a pass or delete run data during collection.
- Stop for explicit operator approval before every live-provider, independent external, hosted deployment, or public deployment task. Approval for one task never authorizes another.
- Do not tag, publish, or claim public readiness until the collector validates every required gate as passed.

---

## File structure

- Create: `reports/release_evidence.py` — manifest, secret/path/hash, gate, aggregate, and rendering logic.
- Create: `benchmarks/external_connector_acceptance.py` — connector receipt schema, sanitization, and validation.
- Create: `scripts/run_external_connector_acceptance.py` — explicit hosted connector runner that never persists credentials.
- Create: `runs/release/manifest-v1.template.yaml` — complete required-gate inventory with no passing artifacts prefilled.
- Create: `runs/release/manifest-v1.yaml` — concrete exact-candidate manifest created only when external execution begins.
- Create: `tests/test_release_evidence.py` — collector, canonicalization, path, hash, substitution, and secret tests.
- Create: `tests/test_external_connector_acceptance.py` — independence, signer, isolation, revocation, wake, and sanitization tests.
- Modify: `run.py` — offline-only `--release-evidence-report` command and exclusivity rules.
- Create: `tests/test_release_evidence_cli.py` — collector CLI exclusivity and no-network dispatch.
- Modify: `docs/operator-runbook.md` — authorization checkpoints and campaign workflow.
- Modify: `docs/world-os/EXTERNAL-AGENT-ACCEPTANCE.md` — link external receipts only after independent passes.
- Modify: `TASKS.md` and `docs/implementation-status.md` — close gates only after qualifying evidence.

### Task 1: Define the fail-closed manifest and collector core

**Files:**
- Create: `reports/release_evidence.py`
- Create: `runs/release/manifest-v1.template.yaml`
- Create: `tests/test_release_evidence.py`

**Interfaces:**
- Produces: `load_release_manifest(path)`, `collect_release_evidence(manifest_path, *, repo_root)`, `canonical_release_json(result)`, and `render_release_markdown(result)`.
- Consumes: repository-relative receipt paths and SHA-256 digests; performs no network or subprocess calls.
- Returns: one record per required gate plus `overall_status`, `candidate`, `errors`, and `generated_at`.

- [ ] **Step 1: Write failing schema and aggregate tests**

Add tests that build temporary repository fixtures and assert:

```python
from reports.release_evidence import collect_release_evidence


def test_complete_local_manifest_passes_only_for_exact_candidate(tmp_path):
    repo, manifest = release_fixture(tmp_path, status="passed", scope="local")
    result = collect_release_evidence(manifest, repo_root=repo)
    assert result["overall_status"] == "passed"
    assert result["candidate"] == {"commit": "1" * 40, "tree": "2" * 40}


def test_collector_reports_all_missing_required_gates(tmp_path):
    repo, manifest = release_fixture(tmp_path, omit={"oracle_v9", "rumor_pilot"})
    result = collect_release_evidence(manifest, repo_root=repo)
    assert result["overall_status"] == "failed"
    assert {error["gate_id"] for error in result["errors"]} == {
        "oracle_v9", "rumor_pilot"
    }
```

Also cover duplicate gate IDs, unknown schemas, invalid enums, missing artifacts, wrong hashes, receipt/candidate mismatch, dirty-candidate markers, and a visible `blocked` record that fails the aggregate.

Run:

```bash
.venv/bin/python -m pytest tests/test_release_evidence.py -q
```

Expected: import or assertion failures because the collector does not exist.

- [ ] **Step 2: Implement strict manifest loading and required-gate inventory**

Define these constants in `reports/release_evidence.py`:

```python
MANIFEST_SCHEMA = "agent-economy-release-manifest-v1"
RECEIPT_SCHEMA = "agent-economy-release-gate-v1"
EXECUTION_SCOPES = {"local", "live_provider", "independent_external"}
STATUSES = {"passed", "failed", "blocked", "not_run"}
REQUIRED_GATES = {
    "independent_mcp", "hermes_connector", "openclaw_connector",
    "python_connector", "typescript_connector", "semantics10_experiment",
    "semantics10_hosted_ui", "semantics10_hosted_ops", "oracle_v9",
    "rumor_pilot", "production_acceptance", "provenance_audit",
    "dependency_license_secret_audit", "hosted_backup_restore",
    "tenant_isolation_load", "deployment_receipt",
}
```

Require gate ID, receipt path, and SHA-256 in each manifest record. Require schema, gate ID, candidate, execution scope, status, start/end UTC, sanitized command, configuration hash, bounded environment identity, summary, artifacts, verifier, and reviewer notes in every receipt. Reject duplicate IDs and extra enum values before reading artifacts.

Create `runs/release/manifest-v1.template.yaml` with all 16 gates. Each starts as `status: not_run` with empty receipt and hash fields, which must collect as incomplete.

- [ ] **Step 3: Restrict paths and verify content identity**

Resolve every receipt and artifact beneath `repo_root` after `Path.resolve()`. Reject absolute paths, parent traversal, escaping symlinks, missing/non-regular files, SQLite sidecars, and SHA-256 mismatches. Sort errors by gate ID and error code for deterministic output. Add a mutation test for every rejection.

- [ ] **Step 4: Add secret-canary and privacy validation**

Scan manifest/receipt strings, commands, summaries, notes, and text artifacts for credential field names, authorization syntax, PEM private keys, JWT-shaped values, provider-key prefixes, OAuth codes, cookie headers, and test canary `AE_RELEASE_SECRET_CANARY_7b42`. Accept only bounded environment facts such as OS, architecture, tool/client versions, deployment digest, and hosted-origin SHA-256.

- [ ] **Step 5: Pass focused tests and commit the core**

```bash
.venv/bin/python -m pytest tests/test_release_evidence.py -q
git diff --check
git add reports/release_evidence.py runs/release/manifest-v1.template.yaml tests/test_release_evidence.py
git commit -m "feat: add fail-closed release evidence collector"
```

Expected: tests pass and the commit contains only the collector core, template, and tests.

### Task 2: Add canonical output and an offline-only CLI

**Files:**
- Modify: `reports/release_evidence.py`
- Modify: `run.py`
- Create: `tests/test_release_evidence_cli.py`
- Modify: `tests/test_release_evidence.py`

**Interfaces:**
- Produces: `write_release_evidence_package(manifest_path, output_dir, *, repo_root)` returning JSON and Markdown paths.
- CLI: `.venv/bin/python run.py --release-evidence-report runs/release/manifest-v1.yaml --output reports/out/release-v1`.
- Constraint: report generation is offline and mutually exclusive with run, replay, fork, serve, experiment, provider preflight, and live-approval flags.

- [ ] **Step 1: Write failing canonicalization and CLI tests**

Test sorted-key UTF-8 JSON with a final newline and byte-identical repeated output. Test Markdown gate ordering, scope/status columns, all validation errors, candidate identity, and artifact hashes. Monkeypatch socket, subprocess, and provider entry points to raise so the CLI proves it never invokes them.

Parameterize conflicts with `--ticks`, `--serve`, `--resume`, `--replay`, `--fork`, `--experiment`, `--acceptance-run`, `--oracle-campaign-run`, `--preflight-live`, and `--approve-live-inference`.

- [ ] **Step 2: Implement deterministic atomic writers**

Write a temporary sibling, flush and `os.fsync`, then publish with `os.replace`. Emit authoritative `release-evidence.json` and deterministic reviewer `release-evidence.md`. Exit `0` only for an overall pass; incomplete/blocked/failed manifests still write both files and exit nonzero.

- [ ] **Step 3: Wire the CLI before world initialization**

Extend the current exclusivity validation and require `--output`. Do not create an overlapping parser path.

```bash
.venv/bin/python -m pytest tests/test_release_evidence.py tests/test_release_evidence_cli.py -q
.venv/bin/python run.py --release-evidence-report runs/release/manifest-v1.template.yaml --output reports/out/release-template
```

Expected: tests pass; the template writes deterministic failed reports, names every missing gate, exits nonzero, and uses no network.

- [ ] **Step 4: Commit the offline report path**

```bash
git add reports/release_evidence.py run.py tests/test_release_evidence.py tests/test_release_evidence_cli.py
git diff --cached --check
git commit -m "feat: render release evidence offline"
```

### Task 3: Build independent external-connector receipt tooling

**Files:**
- Create: `benchmarks/external_connector_acceptance.py`
- Create: `scripts/run_external_connector_acceptance.py`
- Create: `tests/test_external_connector_acceptance.py`
- Modify: `docs/operator-runbook.md`

**Interfaces:**
- Produces: `validate_external_connector_receipt(receipt, *, expected_candidate, expected_connector)` and `write_external_connector_receipt(result, output_path)`.
- Runner connectors: `independent_mcp`, `hermes`, `openclaw`, `python`, and `typescript`.
- Receipts contain public hashes and executed receipt identifiers; credentials remain process-only.

- [ ] **Step 1: Write failing receipt-contract tests**

Require client name/version, independent signer, candidate commit/tree, hosted-origin SHA-256, tenant/run/actor/scope IDs, public request/response hashes, executed receipt IDs/hashes, revocation, and cross-tenant isolation. MCP requires discovery and protected-resource proof; Hermes/OpenClaw require exactly three completed wakes; Python/TypeScript require authorized submit/read flows.

Reject loopback/private origins, `execution_scope: local`, signer identity equal to the server operator, short wake sets, missing receipt reads, failed revocation/isolation, tokens, raw private payloads, and candidate mismatches.

- [ ] **Step 2: Implement the pure validator and atomic writer**

Keep validation transport-independent. Normalize timestamps/IDs, hash only explicitly public bodies, redact transport exceptions from notes, and refuse to overwrite an existing receipt with different bytes.

- [ ] **Step 3: Implement the explicit hosted runner**

Accept connector type, HTTPS base URL, candidate commit/tree, credential-file path, output path, and signer label. Read the mode-600 credential file without printing it; refuse loopback/private targets; run only the selected connector; verify submit/read/revocation/isolation; sanitize; then call the pure writer. Never create tenants, deploy, or authorize spend implicitly.

- [ ] **Step 4: Verify locally without claiming independent evidence**

```bash
.venv/bin/python -m pytest tests/test_external_connector_acceptance.py tests/test_external_agent_gateway.py tests/test_hosted_app.py -q
.venv/bin/python -m compileall benchmarks/external_connector_acceptance.py scripts/run_external_connector_acceptance.py
```

Expected: tests pass; local smokes remain `execution_scope: local` and are ineligible for the five external gates.

- [ ] **Step 5: Document and commit the harness**

Document separate approval boxes for all five connectors, retention, and the rule that one approval cannot cover another.

```bash
git add benchmarks/external_connector_acceptance.py scripts/run_external_connector_acceptance.py tests/test_external_connector_acceptance.py docs/operator-runbook.md
git diff --cached --check
git commit -m "feat: verify independent connector receipts"
```

### Task 4: Execute the five independent external connector gates

**Files:**
- Create: `benchmarks/receipts/release-v1/independent-mcp.json`
- Create: `benchmarks/receipts/release-v1/hermes.json`
- Create: `benchmarks/receipts/release-v1/openclaw.json`
- Create: `benchmarks/receipts/release-v1/python-client.json`
- Create: `benchmarks/receipts/release-v1/typescript-client.json`
- Create: `runs/release/manifest-v1.yaml`
- Modify: `docs/world-os/EXTERNAL-AGENT-ACCEPTANCE.md`

**Interfaces:**
- Consumes: clean candidate commit/tree, hosted HTTPS test tenant, independent clients/signers, and separately approved credentials.
- Produces: five `independent_external` receipts, each independently hashed into the candidate manifest.

- [ ] **Step 1: Freeze the candidate before external execution**

```bash
git status --short
git rev-parse HEAD
git rev-parse HEAD^{tree}
git diff --check
```

Expected: release source is clean and the candidate commit/tree are copied into `runs/release/manifest-v1.yaml`. Any later implementation change invalidates these receipts for release use.

- [ ] **Step 2: Stop for explicit external-test authorization**

Record hosted target, tenant, connector, signer, retention, and infrastructure cost separately for each client. Confirm the credential file is ignored and mode `600` without displaying it.

- [ ] **Step 3: Run all five clients separately**

Invoke `scripts/run_external_connector_acceptance.py` once per connector and store each sanitized result under `benchmarks/receipts/release-v1/`. A failed or blocked client retains its own immutable receipt; a retry uses a new receipt identity.

- [ ] **Step 4: Verify offline and update the checklist only after passes**

```bash
.venv/bin/python -m pytest tests/test_external_connector_acceptance.py -q
.venv/bin/python run.py --release-evidence-report runs/release/manifest-v1.yaml --output reports/out/release-v1
```

Expected: the aggregate still fails because later gates are pending, while these five gates individually show `passed` and `independent_external`. Only then mark the external rows in `docs/world-os/EXTERNAL-AGENT-ACCEPTANCE.md`.

- [ ] **Step 5: Commit external receipts and manifest hashes**

```bash
git add benchmarks/receipts/release-v1 runs/release/manifest-v1.yaml docs/world-os/EXTERNAL-AGENT-ACCEPTANCE.md
git diff --cached --check
git commit -m "evidence: record independent connector acceptance"
```

### Task 5: Produce frozen Semantics 10 experiment and hosted receipts

**Files:**
- Verify: `benchmarks/commons_acceptance.py`
- Verify: `tests/test_commons_acceptance.py`
- Verify: `research/commons_supplier_warning_experiment.py`
- Verify: `tests/test_commons_supplier_warning_protocol.py`
- Create: `benchmarks/receipts/release-v1/semantics10-experiment.json`
- Create: `benchmarks/receipts/release-v1/semantics10-hosted-ui.json`
- Create: `benchmarks/receipts/release-v1/semantics10-hosted-ops.json`
- Modify: `runs/release/manifest-v1.yaml`

**Interfaces:**
- Consumes: frozen multi-arm commitment and exact candidate deployment.
- Produces: distinct experiment, hosted-browser, and hosted-operations receipts; none substitutes for another.

- [ ] **Step 1: Re-run maintained local mechanics gates**

```bash
.venv/bin/python -m pytest tests/test_agent_commons.py tests/test_commons_acceptance.py tests/test_commons_supplier_warning_protocol.py tests/test_external_agent_gateway.py -q
```

Expected: all tests pass; this is implementation evidence only.

- [ ] **Step 2: Validate the frozen experiment contract**

Require all precommitted arms, seeds, hypotheses, exposure definitions, moderation paths, contamination exclusions, candidate identity, and artifact paths. Do not edit the commitment after observing an arm. Stop if an arm is missing or the candidate differs.

- [ ] **Step 3: Stop for separate experiment and hosting approvals**

Record maximum provider spend, hosted target, retention, duration, model route, and rollback owner. Experiment approval does not authorize hosting; hosting approval does not authorize public deployment.

- [ ] **Step 4: Run every frozen arm and one exact offline replay per arm**

Capture feed/post/explicit-read exposure, moderation, supplier-warning branches, ledger integrity, run/database hashes, provider provenance, and replay comparisons. Missing, excluded, substituted, or contaminated arms fail `semantics10_experiment`.

- [ ] **Step 5: Capture hosted UI and operations evidence**

In Chromium, verify feed/post/read/moderation, privacy, refresh/deep links, responsive layouts, and zero console/network errors. Independently record health, bounded load, tenant isolation, metrics/logs, snapshot/restore, and deployment digest. Sanitize screenshots/traces before hashing them.

- [ ] **Step 6: Add all three hashes and verify offline**

```bash
.venv/bin/python run.py --release-evidence-report runs/release/manifest-v1.yaml --output reports/out/release-v1
```

Expected: all three Semantics 10 gates pass individually; aggregate remains failed while later gates are pending.

### Task 6: Run the fresh ten-arm V9 MiniMax Oracle campaign

**Files:**
- Verify: `runs/oracle/manifest-v9.template.yaml`
- Verify: `runs/oracle/commitment-v9.yaml`
- Verify: `runs/oracle/v9-seed-7381-control.yaml` through `runs/oracle/v9-seed-7390-rumor.yaml`
- Verify: `reports/oracle_campaign.py`
- Create: `reports/out/oracle-calibration-v9/`
- Create: `benchmarks/receipts/release-v1/oracle-v9.json`
- Modify: `runs/release/manifest-v1.yaml`

**Interfaces:**
- Consumes: commitment SHA-256 `8a1845ebe9e916b8618a1c17170dc8a2b439c929ea1e1118670e21683c341a8e`, seeds 7381-7390, odd control/even rumor, and the exact MiniMax-M3 Oracle route.
- Produces: ten eligible source receipts, ten one-time exact offline replay receipts, and one aggregate campaign receipt.

- [ ] **Step 1: Run offline configuration and validator checks**

```bash
.venv/bin/python -m pytest tests/test_oracle_campaign.py tests/test_acceptance.py tests/test_recorded_replay_golden.py tests/test_replay_source_lifecycle.py -q
.venv/bin/python run.py --preflight --config runs/oracle/v9-seed-7381-control.yaml
```

Expected: focused tests and free preflight pass. Preflight is not V9 evidence.

- [ ] **Step 2: Stop for explicit V9 live-inference approval**

Record ten profiles, MiniMax-M3, Oracle-only live routing, `$25` per-run cap, at most `$250` campaign exposure, pricing/cache policy, duration, credential-file location, and retention. Confirm no V1-V8 artifact is referenced.

- [ ] **Step 3: Execute each immutable arm once**

Run every committed profile in seed order:

```bash
AE_V9_PROFILES=(
  runs/oracle/v9-seed-7381-control.yaml
  runs/oracle/v9-seed-7382-rumor.yaml
  runs/oracle/v9-seed-7383-control.yaml
  runs/oracle/v9-seed-7384-rumor.yaml
  runs/oracle/v9-seed-7385-control.yaml
  runs/oracle/v9-seed-7386-rumor.yaml
  runs/oracle/v9-seed-7387-control.yaml
  runs/oracle/v9-seed-7388-rumor.yaml
  runs/oracle/v9-seed-7389-control.yaml
  runs/oracle/v9-seed-7390-rumor.yaml
)
for AE_V9_PROFILE in "${AE_V9_PROFILES[@]}"; do
  .venv/bin/python run.py --config "$AE_V9_PROFILE" --oracle-campaign-run --approve-live-inference || exit 1
done
```

Do not parallelize claims unless the existing contract supports it. Preserve failed/blocked arms; never substitute seeds or archived receipts.

- [ ] **Step 4: Build and validate the aggregate campaign package**

Create the concrete manifest using only the ten emitted V9 source/replay receipt paths and hashes, then run:

```bash
.venv/bin/python run.py --oracle-calibration-report runs/oracle/manifest-v9.yaml --output reports/out/oracle-calibration-v9
```

Expected: ten eligible runs, 60 resolved forecasts, both outcomes, end-to-end p90 below 60 seconds, aggregate Brier below `0.25`, exact replay for every arm, no fallback/live replay dispatch, and no V1-V8 evidence.

- [ ] **Step 5: Wrap the aggregate in the release receipt**

Hash the V9 manifest, source/replay receipts, aggregate JSON/Markdown, and candidate into `oracle-v9.json`; add it to the release manifest. A campaign failure stays `failed`, not `blocked`.

### Task 7: Run the capped 30-day live rumor pilot

**Files:**
- Verify: `runs/acceptance/pilot.yaml`
- Verify: `reports/acceptance.py`
- Create: `benchmarks/receipts/release-v1/rumor-pilot.json`
- Modify: `runs/release/manifest-v1.yaml`

**Interfaces:**
- Consumes: corrected pilot profile, exact candidate, live approval, and experiment/phenomena evidence.
- Produces: terminal source receipt, integrity evidence, and exact offline replay bound to the 30-day run.

- [ ] **Step 1: Prove free mechanics and profile inheritance**

```bash
.venv/bin/python run.py --preflight --config runs/acceptance/pilot.yaml
.venv/bin/python -m pytest tests/test_acceptance.py tests/test_recorded_replay_golden.py tests/test_replay_source_lifecycle.py tests/test_oracle_campaign.py -q
```

Expected: preflight and focused tests pass with no provider spend.

- [ ] **Step 2: Stop for explicit pilot approval**

Record profile, model routes, committed hard budget, duration, provider account, credential-file location, candidate, and retention. This approval covers only the 30-day pilot.

- [ ] **Step 3: Execute the pilot without changing the candidate**

```bash
set -o pipefail
.venv/bin/python run.py --config runs/acceptance/pilot.yaml --acceptance-run --approve-live-inference 2>&1 | tee reports/out/rumor-pilot-run.log
```

Parse the standard structured run-open line from the preserved terminal log and run:

```bash
AE_PILOT_RUN_ID=$(sed -n 's/^\[agent-economy\] run \([^ ]*\) @ tick.*/\1/p' reports/out/rumor-pilot-run.log | tail -1)
test -n "$AE_PILOT_RUN_ID"
.venv/bin/python run.py --acceptance-report "$AE_PILOT_RUN_ID" --output "reports/out/acceptance-$AE_PILOT_RUN_ID"
```

Cross-check the parsed value against the acceptance JSON and source database before using the receipt. Require tick 30, bounded spend, scheduled prediction, rumor exposure/trust/outflow, provider provenance, zero critical failures, integrity, balanced ledgers, checkpoints, and exact replay.

- [ ] **Step 4: Record eligibility without authorizing production**

Hash `rumor-pilot.json` into the manifest. A failure remains failed and stops this campaign. A pass only makes Task 8 eligible for separate approval.

### Task 8: Run the authorized 365-day production acceptance

**Files:**
- Verify: `runs/acceptance/production.yaml`
- Verify: `runs/acceptance/phenomena.template.yaml`
- Create: `benchmarks/receipts/release-v1/production-acceptance.json`
- Modify: `runs/release/manifest-v1.yaml`

**Interfaces:**
- Consumes: passing Task 7 receipt, clean candidate, approved `$200` efficiency boundary, real provider routes, and reviewed phenomena.
- Produces: terminal 365-day source, acceptance package, exact replay, and release receipt.

- [ ] **Step 1: Verify pilot dependency and production profile offline**

Require `rumor_pilot: passed` for the same candidate. Run preflight, inheritance tests, acceptance validators, and a read-only artifact capacity check. Stop on profile/candidate drift.

- [ ] **Step 2: Stop for a new production approval**

Record 365 ticks, configured population near 100, five shocks, six Oracle samples, routes, `$200` efficiency gate, provider hard caps, duration, checkpoint/storage retention, monitoring owner, and interrupt/resume policy.

- [ ] **Step 3: Execute while preserving resumability**

```bash
.venv/bin/python run.py --config runs/acceptance/production.yaml --acceptance-run --approve-live-inference
```

Use only the existing claim/resume contract. Before resuming after overload, interruption, or restart, verify persisted active phase and successful-call reuse; never duplicate actions, charges, checkpoints, or receipts.

- [ ] **Step 4: Generate acceptance and exact replay evidence**

Use the emitted machine-readable run ID with `--acceptance-report`. Require tick 365, population/config match, all shocks, six resolved Oracle checks, reviewed phenomena, provider provenance, spend/efficiency pass, zero critical failures, clean SQLite integrity, balanced ledgers, checkpoint hashes, and one exact offline replay.

- [ ] **Step 5: Hash production evidence into the manifest**

Create `production-acceptance.json` with source/replay/report hashes and candidate identity. The collector remains failed until final audit and deployment gates pass.

### Task 9: Run exact-candidate provenance, dependency, secret, hosted, and deployment gates

**Files:**
- Create: `benchmarks/receipts/release-v1/provenance-audit.json`
- Create: `benchmarks/receipts/release-v1/dependency-license-secret-audit.json`
- Create: `benchmarks/receipts/release-v1/hosted-backup-restore.json`
- Create: `benchmarks/receipts/release-v1/tenant-isolation-load.json`
- Create: `benchmarks/receipts/release-v1/deployment.json`
- Modify: `runs/release/manifest-v1.yaml`

**Interfaces:**
- Consumes: exact candidate and separately approved hosted target.
- Produces: five independent final receipts. Deployment cannot pass before the other four do.

- [ ] **Step 1: Run local exact-candidate audit gates**

```bash
.venv/bin/python -m pip check
.venv/bin/python -m pytest tests/ -q
.venv/bin/python run.py --verify-datasets config/data-manifest.yaml
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

Return to the repository root. Verify `git diff --check`, static-bundle freshness, lockfile identity, licenses, secret scan, provenance coverage, and clean candidate identity. Record environment-gated skips as skips.

- [ ] **Step 2: Stop for hosted backup/restore and isolation/load approval**

Record target, tenant fixtures, load ceiling, snapshot backend, destructive restore scope, rollback, monitoring, retention, and cost. Use a disposable restore target; never overwrite production data.

- [ ] **Step 3: Execute hosted operational gates**

Verify TLS, health, metrics/logs, immutable snapshot, cold restore, password rotation, tenant isolation, revocation, bounded load, and deployment digest. Hash sanitized artifacts into separate backup/restore and isolation/load receipts.

- [ ] **Step 4: Stop for separately authorized deployment**

Require all non-deployment gates to pass offline. Record target, candidate image digest, rollback image, migrations, operator, window, and public-exposure decision. Hosted testing is not public-deployment authorization.

- [ ] **Step 5: Deploy the exact candidate and verify rollback readiness**

Record image/commit/tree, health, smoke, tenant isolation, dashboard/API contract, backup point, rollback result, and external observation. Any rebuild or source mutation restarts candidate-bound gates.

### Task 10: Finalize evidence and authoritative status

**Files:**
- Modify: `runs/release/manifest-v1.yaml`
- Create: `reports/out/release-v1/release-evidence.json`
- Create: `reports/out/release-v1/release-evidence.md`
- Modify: `TASKS.md`
- Modify: `docs/implementation-status.md`
- Modify: `docs/operator-runbook.md`

**Interfaces:**
- Consumes: all 16 qualifying gate receipts on one exact candidate.
- Produces: authoritative passed JSON/Markdown and synchronized human status.

- [ ] **Step 1: Run the final offline collector twice**

```bash
.venv/bin/python run.py --release-evidence-report runs/release/manifest-v1.yaml --output reports/out/release-v1
sha256sum reports/out/release-v1/release-evidence.json reports/out/release-v1/release-evidence.md
.venv/bin/python run.py --release-evidence-report runs/release/manifest-v1.yaml --output reports/out/release-v1
sha256sum reports/out/release-v1/release-evidence.json reports/out/release-v1/release-evidence.md
```

Expected: both commands exit `0`; all 16 gates pass; both sets of hashes match; candidate commit/tree match deployed source.

- [ ] **Step 2: Perform human substitution and privacy audit**

Review every scope, status, signer, candidate, command, configuration hash, artifact hash, and note. Search for secret canaries, credential syntax, private content, absolute paths, mock substitutions, Oracle V1-V8 references, excluded experiment arms, and missing hosted identities. Any finding fails finalization.

- [ ] **Step 3: Update authoritative ledgers only after pass**

Mark only evidenced rows complete in `TASKS.md`, `docs/implementation-status.md`, and operator/external checklists. Link the canonical receipt and exact candidate. Preserve historical diagnostics and do not say public-ready unless the deployment receipt permits that exact claim.

- [ ] **Step 4: Run final documentation and repository gates**

```bash
.venv/bin/python -m pytest tests/test_release_evidence.py tests/test_external_connector_acceptance.py tests/test_documentation.py -q
git diff --check
git status --short --branch
```

Expected: tests pass, diff check is empty, and only intended receipt/status files changed.

- [ ] **Step 5: Commit immutable release evidence**

```bash
git add runs/release/manifest-v1.yaml reports/out/release-v1 benchmarks/receipts/release-v1 TASKS.md docs/implementation-status.md docs/operator-runbook.md docs/world-os/EXTERNAL-AGENT-ACCEPTANCE.md
git diff --cached --check
git commit -m "evidence: complete release readiness campaign"
```

Expected: manifest, receipts, deterministic reports, and truthful status updates are committed. Tagging or pushing still requires an approved publication action.

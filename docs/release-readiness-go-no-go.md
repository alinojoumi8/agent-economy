# Release-readiness go/no-go sheet

Assessment date: 2026-08-26

This sheet is the operating decision surface for the remaining release work.
The [implementation-status ledger](implementation-status.md) remains the
authority for what is implemented; the generated release package remains the
authority for whether one exact candidate passed its gates.

## Current verdict

- **GO — local review baseline:** run the nine-gate `reproducibility-v1`
  profile against a clean candidate. It contacts no providers and authorizes no
  hosted or public operation.
- **HOLD — paid, independent, and hosted execution:** no approval is recorded
  here for provider spend, an independent connector, a hosted target, or a live
  experiment.
- **NO-GO — tag or public deployment:** the fixed 16-gate `production-v1`
  package is not complete. Historical receipts and local passes cannot fill its missing rows.

`PASS` means qualifying evidence exists for the named exact candidate. `READY`
means the implementation and harness exist but the qualifying run still needs
its prerequisites and approval. `HOLD` means do not execute yet. `NO-GO` means
the downstream release decision is prohibited.

## Decision matrix

| Workstream | Fixed production gates | Evidence state | Execution decision | Proof required before the gate can pass |
|---|---|---|---|---|
| Local reproducibility baseline | None; separate nine-gate profile | Candidate-specific package required | **GO** at zero provider spend | Clean commit/tree; all nine local receipts passed; sanitized hashed logs; offline collector status `passed`; clean tree after the fresh dashboard build |
| Independent connectors | `independent_mcp`, `hermes_connector`, `openclaw_connector`, `python_connector`, `typescript_connector` | Local harness exists; five independent receipts are pending | **HOLD** for a separate approval per connector | Public HTTPS test tenant; independent client and signer; native result, detailed finalization receipt, and generic wrapper; discovery/protected-resource proof for MCP; exactly three completed wakes for Hermes/OpenClaw; submit/read proof for Python/TypeScript; revocation and cross-tenant isolation |
| Semantics 10 rollout | `semantics10_experiment`, `semantics10_hosted_ui`, `semantics10_hosted_ops` | Code and local synthetic acceptance exist; three rollout receipts are pending | **HOLD** for separate experiment and hosting approvals | Frozen multi-arm commitment; every arm plus exact replay; exposure, moderation, contamination, ledger, and provider proof; Chromium feed/post/read/privacy/deep-link evidence; health, bounded load, isolation, logs/metrics, snapshot/restore, and deployment digest |
| V9 Oracle calibration | `oracle_v9` | Ten fresh live arms are pending | **HOLD** for a campaign-specific paid approval | Seeds 7381–7390; only `minimax/MiniMax-M3` live; commitment hash match; `$25` per-run cap; 60 resolved forecasts; both outcomes; aggregate Brier below `0.25`; p90 below 60 seconds; exact replay for every arm; no V1–V8 substitution |
| Corrected 30-day rumor pilot | `rumor_pilot` | Corrected profile and validators exist; qualifying live run is pending | **HOLD** for a pilot-only paid approval | Exact candidate/profile, provider routes and hard budget, terminal tick 30, rumor exposure/trust/outflow, provenance, zero critical failures, integrity, balanced ledgers, checkpoint hashes, and exact offline replay |
| 365-day production acceptance | `production_acceptance` | Free rehearsal is historical; qualifying live run is pending | **NO-GO** until the same-candidate rumor gate passes, then **HOLD** for a new approval | 365 ticks, configured population, five shocks, six resolved Oracle checks, reviewed phenomena, real-provider provenance, `$200` efficiency boundary and hard caps, resumability, integrity, balanced ledgers, checkpoints, and exact replay |
| Exact-candidate local audit | `provenance_audit`, `dependency_license_secret_audit` | Historical audit exists; fresh candidate audit is pending | **READY** after candidate freeze; no provider spend | Full test/build contract, pinned datasets and locks, provenance coverage, license notices, dependency audits, current-tree/history secret scans, static-bundle identity, diff hygiene, and clean candidate identity |
| Hosted resilience and isolation | `hosted_backup_restore`, `tenant_isolation_load` | Local hosted implementation evidence exists; qualifying target receipts are pending | **HOLD** for a disposable hosted target and explicit operational approval | TLS/health, immutable snapshot, cold restore without production overwrite, password rotation, tenant isolation, revocation, bounded load, monitoring evidence, retention, rollback, and deployment digest |
| Deployment | `deployment_receipt` | Not run | **NO-GO** until the other 15 production gates pass, then **HOLD** for separate deployment approval | Exact image/commit/tree, migrations, backup point, health and smoke checks, tenant/API/dashboard contracts, rollback image and tested rollback, operator/window, target, and public-exposure decision |

## Required order

1. Freeze a clean candidate and pass `reproducibility-v1`.
2. Record separate approvals before each independent connector, Semantics 10
   experiment/hosting stage, or paid provider campaign.
3. Complete the five connector receipts and three Semantics 10 receipts without
   treating one client, arm, browser check, or hosted check as a substitute for
   another.
4. Run V9, then the corrected 30-day rumor pilot. A rumor pass makes the
   365-day campaign eligible for discussion; it does not authorize it.
5. Run the separately approved 365-day campaign, then the fresh exact-candidate
   local and hosted final gates.
6. Deploy only after the first 15 production gates pass, then run the offline
   collector twice and complete the human privacy/substitution audit.

Any implementation change, generated-bundle drift, candidate mismatch,
credential leak, substituted client/model/arm, missing replay, failed gate, or
unreviewed private artifact stops the sequence. A retry receives a new immutable
receipt identity; failed evidence is retained as failed rather than relabelled.

## Approval record required before non-local work

Each approval must name one workstream, exact candidate commit/tree, target or
provider account, model/client identity, maximum spend or infrastructure cost,
duration, credential-file location without exposing its contents, retention,
monitoring owner, stop conditions, and rollback or interruption owner. Approval for one row never authorizes another row.

The first paid-milestone discussion should therefore choose one bounded
workstream and its owner, budget, target, and success receipt. This sheet does not make that choice and does not authorize spend.

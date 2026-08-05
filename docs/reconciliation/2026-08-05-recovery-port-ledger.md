# Recovery Port Ledger — 2026-08-05

## Scope and preserved evidence

- Port target: `codex/reconcile-recovery-20260805`, based on current `main` (`3ba4e25` at worktree creation).
- Immutable source: `codex/reconcile-release`; divergence at audit was `50` main-only and `26` source-only commits.
- Source diff: 20 files, 8,208 insertions, and 41 deletions relative to its merge base with current main.
- Historical candidate: `820e5bf35e.db`, opened only with SQLite URI flags `mode=ro&immutable=1`.
- Candidate SHA-256: `3314105a4655d15652fc61a2999e17a61c97a73c5f74580b66f3e96fef7eee6a`.
- Candidate integrity and state: `PRAGMA quick_check=ok`; run `820e5bf35e`, completed tick 826, active tick 827, next phase `MORNING`, status `running`.
- Existing `820e5bf35e.db-shm` and `820e5bf35e.db-wal` sidecars were observed and left untouched. This historical run is diagnostic-only and is not eligible evidence for the port.

## Commit dispositions

The disposition vocabulary is limited to `already-on-main`, `port-unchanged`, `port-synthesized`, `superseded`, and `diagnostic-only`.

| Source | Subject | Disposition | Port / rationale |
|---|---|---|---|
| `22bf122` | define reconciliation and recovery design | superseded | Replaced by the approved 2026-08-05 design and implementation plans. |
| `281e3df` | plan recovery UI and release evidence | superseded | Replaced by the approved investigation, World OS, and release-evidence plans. |
| `3280d01` | add sustainable recovery economics | port-unchanged | `7f45a9f`; pure `world.recovery` contract and tests. |
| `cb26cfa` | clarify recovery validation boundary | superseded | Its invariants are carried by the 2026-08-05 plan and this ledger. |
| `7ea5d94` | harden recovery economics and profile validation | port-unchanged | `6c03142`; strict settings validation. |
| `59d316d` | correct recovery demand units and composition | port-unchanged | `1f79de7`; quantity-based completed-window demand. |
| `57dd40c` | record recovery economics safeguards | superseded | Safeguards are executable tests and documented in the current plan. |
| `3684cfd` | gate supply and workforce recovery by viable economics | port-synthesized | `a3258e8`; integrated with current inventory-aware demand and workforce recovery. |
| `2f6f9d6` | enforce recovery hiring at actual wages | port-synthesized | `9afa60e`; preserved current action receipts and deterministic workforce overlays. |
| `a8bf316` | preserve stale recovery offer rejection | port-unchanged | `e894835`; executor stale reason remains authoritative. |
| `9d8d6e0` | retain bounded recovery checkpoints | port-synthesized | `2fe0e92`; integrated after current same-tick checkpoint catalog deduplication. |
| `0397fc1` | harden checkpoint retention safety | port-synthesized | `71f026d`; canonical paths, strict integer config, and symlink exclusions. |
| `52565d3` | add supply recovery acceptance receipt | port-synthesized | `652b4d6`; added report CLI beside current activation and Oracle modes. |
| `486cfed` | harden supply recovery receipt evidence | port-synthesized | `2170b8a`; report dispatch occurs before logging to preserve read-only evaluation. |
| `0dd0a5f` | close supply recovery evidence gaps | port-unchanged | `d5126a4`; schema, status, and producer identity validation. |
| `2426b67` | validate supply recovery lifecycle evidence | port-unchanged | `2356da6`; terminal lifecycle evidence contract. |
| `440482a` | enforce supply recovery terminal evidence | port-unchanged | `1054e38`; acquirer identity and terminal evidence. |
| `22c8214` | harden supply recovery receipt contracts | port-unchanged | `5a993f8`; strict persisted types, horizons, and ordering. |
| `826b8d9` | prove merger acquirer lifecycle timing | port-unchanged | `6f557d1`; same-tick event-order evidence. |
| `b88c65b` | reject acquirer bankruptcy markers | port-unchanged | `425c8f3`; incompatible lifecycle markers fail closed. |
| `b2dab53` | retain acquirer marker evidence | port-unchanged | `5a889c3`; all independent invalid markers remain in the receipt. |
| `d8cbd5e` | recover supply from stockout demand | port-synthesized | `7d3e8f9`; current price policy and action validation now share the recovery floor. |
| `fd3b4eb` | price recovery wages by pay interval | port-unchanged | `3a44fb8`; persisted incumbent pay intervals determine the price floor. |
| `eecf592` | converge supply recovery capacity | port-synthesized | `1b511ea`; preserved current currency-safe labor queries while filtering closed vacancies only for recovery. |
| `9b19768` | gate recovery labor cleanup | port-synthesized | `aa2a06c`; current market-phase offer expiry remains intact and cleanup is activation-gated. |
| `d63d48a` | reconcile stale jobs on recovery activation | port-unchanged | `c10fe58`; activation also terminalizes applications from already-closed stale jobs. |

## Synthesized conflict ledger

| Area | Current-main function | Source function | Deciding invariant | Regression evidence |
|---|---|---|---|---|
| Household goods choice | `agents.policies._select_stocked_firm` | recovery capacity selector | Feature-off keeps legacy cheapest choice; either current inventory-aware mode or active supply recovery may distribute demand by stock. | `test_recovery_selection_uses_capacity_and_application_load_but_feature_off_is_legacy` plus current inventory-aware tests. |
| Job choice | `agents.policies.citizen_decision` | `_select_open_job` | Feature-off keeps deterministic highest wage; application load affects selection only when explicitly activated. | Supply recovery selection test and current application-aware property tests. |
| Founder staffing | `agents.policies.founder_decision` / `workforce_recovery_actions` | recovery hiring limits | Economic floor/ceiling and live demand are authoritative without removing the current deterministic workforce overlay. | Founder recovery tests and `tests/test_workforce_recovery_bugs.py`. |
| Context construction | `ContextBuilder.build(..., firm_id=...)` | recovery context injection | Current explicit multi-firm ownership, currency, communications, and civic context survive; recovery facts are additive and activation-gated. | Context activation, completed-tick demand, currency, and current PRD tests. |
| Action boundary | `AgentRuntime.execute_decisions` and `ActionExecutor` | recovery pre/post hooks | Every attempted action remains receipt-visible; stale executor reasons win, while viable wage/price checks fail closed before mutation. | Runtime actual-wage, stale-offer, price-floor, and proposal tests. |
| Genesis | `Genesis._firms` / `_staff_firm` | recovery seed hire | Preserve current configured/calibrated headcount behavior; an active tick-zero recovery profile may seed at most one economically viable floor-wage worker. | Genesis activation and viable-floor tests. |
| Checkpoints | `World.checkpoint` | `_prune_checkpoints` | Current same-tick deduplication occurs before bounded retention; only canonical current-run non-symlink artifacts are eligible. | 20 checkpoint retention tests. |
| CLI/report dispatch | `run.main` | supply recovery report mode | Report evaluation is read-only and produces no logs or SQLite sidecars unless `--output` is explicit; current activation/Oracle CLI remains valid. | Supply recovery CLI artifact tests. |
| Labor expiry | `Labor.expire_stale_jobs(..., phase=...)` | recovery terminalization flag | Current incompatible-offer expiry always runs; pending application cleanup occurs only after recovery activation and includes older closed vacancies. | Labor IPO and late-activation PRD tests. |
| Receipt lifecycle | `reports.supply_recovery` | source receipt series | Strict types, completed horizon, event order, checkpoint manifests, and all independent lifecycle invalidities remain observable. | Mutation matrix in `tests/test_supply_recovery_report.py`. |

## Port structure note

The source branch kept receipt orchestration, checkpoint validation, and evidence checks in `reports/supply_recovery.py`. The approved plan proposed optional helper modules, but the audited source never contained them. This port retains the tested public module to avoid an unneeded refactor during reconciliation; any later split must preserve byte-equivalent receipt behavior.

## Focused verification

- Recovery economics and integration: 39 focused tests passed after stockout and price-floor integration.
- Checkpoint retention: 20 tests passed.
- Recovery plus checkpoint combined gate: 60 tests passed.
- Labor lifecycle: 13 tests passed before the final activation-gating additions; all newly added activation cases passed individually.
- Receipt mutation suite was run green after each source hardening slice; a fresh full-suite result is required before merge.

# Population finance entry points — W5 integration evidence

The existing loan and older VC action paths preserve the intended departure
boundary in a combined 15-day World workflow. New personal credit requests end
on departure; already disbursed debt continues to settle. A company retains its
pending financing requests, receives a resident operator and can receive funding
while its original founder remains an outside shareholder.

This follow-up advances the participation inventory and mixed scenario matrix
in [the open population specification](2026-09-09-open-population-boundary.md).
It adds integration coverage and documents existing behavior. Schema 25, the
maximum supported Semantics 20 and the unregistered migration remain unchanged.
W5 admission, native acceptance, full CI and W6–W9 remain open.

## Reviewed paths and decisions

| Path | Admission or settlement rule | Evidence |
| --- | --- | --- |
| `ActionExecutor.execute_action` | The Semantics-21 actor check runs before handler dispatch. A new outside action requires an explicitly allowed outside operation. Rejected attempts retain proposal/result evidence. | Current source and existing population action suites. |
| `pitch_vc` → `VentureCapital.pitch` | Actor admission, startup authorization and current firm control precede the pitch. | Current caller, plus the new genesis application through the actual executor. |
| `fund_pitch` / `decline_pitch` → `VentureCapital.fund` / `decline` | Actor admission and current VC-role checks precede these supported commands. The older funding action has not been removed by typed startup contracts. | Current callers; a recorded resident VC funds the company's retained pitch on day 3. |
| `VentureCapital.run_nightly` | Expire stale pitches and record write-offs on bankrupt portfolio companies. These are institutional outcomes of existing records. | Current World caller and service source; do not filter existing positions by owner residence. |
| `VentureCapital.portfolio` | Read retained funded/written-off positions. | Current agent-context and server read callers; ownership remains inspectable. |
| `apply_loan` / `approve_loan` | Actor admission, company control or credit-officer role, request status and existing currency rules precede application/disbursement. | Actual executor applications, rejected expired personal request and accepted company credit. |
| `PopulationCommitments.end_person` | Expire the person's pending loan application at departure. The company remains a separate borrower. | One immutable loan-application ending in the workflow; existing rollback and commitment suites. |
| `Bank.disburse_loan` / `process_due_loans` | Disbursement is an institutional settlement primitive reached by approval or explicit fixture seeding. Due payments retain valid debt even while the borrower is outside. | Current callers; actual NIGHT_CLOSE repayments on days 7 and 14. |

The graph still reports no callers for `VentureCapital.fund`, although the
current `_do_fund_pitch` source calls it. Some enriched match coordinates also
refer to adjacent methods. The saved inventory resolves raw matches against
the current AST, records file hashes and keeps these graph limitations explicit.
An empty graph edge is not evidence that a supported command is unused.

This is a bounded credit/VC review, not the complete financial or runtime
inventory. Central-bank support, other financial instruments and the remaining
authority, economic and observer surfaces keep their separate acceptance work.

## Executed workflow

`tests/test_population_finance_workflow.py` declares identical genesis business
and credit records in the source and replay. Person 23 owns 60 of 100 shares;
resident person 24 owns 40 and becomes operator when person 23 departs. The
company starts with 10,000 cents transferred from its founder. A 7,000-cent
personal loan has four weekly, zero-interest instalments. A separate personal
application, company application and company pitch begin pending. A foreign
currency account holds 37 units of that currency's minor denomination.

The credit-officer and VC policy responses use an explicit recorded schedule;
other agent policies keep their existing behavior. This supplies controlled
integration evidence rather than autonomous underwriting, company formation,
empirical price discovery or native population growth.

| Day | Required observation |
| --- | --- |
| 1 | Both applications remain pending; person 23 remains local. |
| 2 | Actual departure expires only the personal request; the company request survives and person 24 takes control. |
| 3 | A resident officer's approval of the expired personal request is rejected. A resident VC funds the retained company pitch with 2,000 cents for 25 new shares. The outside founder retains 60 shares. |
| 4 | The resident officer approves the company's retained 3,000-cent loan request. |
| 5 | Source and replay each close after NIGHT_CLOSE and reopen before completing the day. |
| 7 | Actual scheduled repayment reduces the outside person's original principal from 7,000 to 5,250 cents. |
| 12 | The same person returns with the same checking identity and foreign account; company control stays with the successor. |
| 14 | A second actual repayment reduces original principal to 3,500 cents. |
| 15 | All final facts, balances and exact recorded replay still agree. |

Every completed day checks ownership, personal/company application statuses,
current residence, account identity, the foreign balance, loan principal and
ledger reconciliation. Closed source and replay comparisons cover the exact
replay contract and hashes for events, accounts, ledger entries, loans,
applications, pitches, shares, action proposals and commitment endings. The
source exports to v8 Parquet and passes source-backed bundle validation. Its
bytes and mtime stay unchanged and no SQLite sidecars remain. Provider cost is
zero.

## Receipts and remaining work

The dedicated case passed in **72.47 seconds** on Windows/Python 3.11.15.
The bounded runner exited 0 in 73.48 seconds, retained **40,917,100 bytes** under
`C:/Users/matri/.codex/tmp/ae-1d695ca2`, and left **113,853,325,312 bytes free**.
All 1,150 source files retained their hashes/mtimes during the test and staging
remained empty. Receipt prefix:
`tmp/estate-finality-population-finance-workflow-r1`.

The case is included in the existing `research-population-commons` CI job
for Ubuntu/Windows and Python 3.11/3.12. Its exact expanded target list passed
**149 tests in 319.91 seconds** locally on Windows/Python 3.11.15. The bounded
runner exited 0 in 320.98 seconds, retained **737,043,057 bytes** under
`C:/Users/matri/.codex/tmp/ae-d72a89a0`, and left **113,070,792,704 bytes free**.
All 1,151 source files kept their hashes/mtimes and staging stayed empty. The
dedicated case is included in that count. Receipt prefix:
`tmp/estate-finality-population-finance-workflow-ci`.

The closed source and replay each contain **20,115,456 bytes**. Independent
read-only inspection confirms the two scheduled payments, the three recorded
financial decisions, both loan balances, all three shareholder quantities and
the 37-unit IVC holding. The graph/source inventory and artifact audit are saved
under `C:/Users/matri/.codex/tmp/ae-eac8253d` as
`finance-entrypoints-inventory.json` and `finance-workflow-artifact-audit.json`.

The documentation/version-admission check runs `tests/test_documentation.py`
and `tests/test_population_residence_history.py::test_unfinished_population_boundary_is_not_advertised`;
its terminal result uses receipt prefix
`tmp/estate-finality-population-finance-workflow-docs-final`. Only the local
Windows/Python 3.11 integration targets were executed here. Other CI platforms,
the complete CI workflow and the existing Starlette/httpx warning remain open.

Continue the undispositioned participation inventory and the complete declared
mixed scenario matrix before registering the draft. Preserve the original
native campaign, both frozen environments and the interrupted verifier evidence;
this short integration case does not complete their outstanding acceptance.
Focused work retains the 40 GiB free-space floor. Do not launch a new native
campaign under the elapsed original budget.

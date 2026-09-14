# Estate cash and bank principal — W5 checkpoint

Status: implemented with focused local validation. Opt-in Semantics 19, additive schema 24,
hash-contract-v6. The earlier contracts and migrations remain frozen.

## Problem and resulting behavior

The earlier death transition checks only the primary wallet when repaying a
bank loan. A person who moved to a CAD primary wallet can still own USD savings,
yet leave a USD loan unpaid and distribute those savings to an heir. Unpaid
principal is marked defaulted without posting its loss to bank equity.

Semantics 19 inventories every personally owned checking, savings and FX wallet
after collection of available earned wages. It pays active personal bank loans
from all wallets in the loan's currency, records any principal write-off against
that bank's equity, then distributes residual positive cash. Each component has
immutable receipts linked to the ledger. The public event identifies the
settlement without publishing creditor amounts or private bank balances.

## Declared research policy

1. Settle active **principal** in ascending loan ID order. Within each currency,
   consume wallets in account ID order. This is a declared priority assumption,
   not a jurisdiction's probate law or a calibrated creditor bargaining model.
2. Use the creditor bank's declared currency. Never net different currencies,
   synthesize an exchange rate, spend a wage receivable, or borrow from an heir.
3. Preserve the existing reserves-funded credit model: cash principal goes to
   the creditor's reserve account. A shortfall debits bank equity and credits
   the same-currency system loss account. Close outstanding principal to zero;
   use `paid` when fully recovered and `default` when a loss remains. The ordinary
   due-loan processor cannot charge the same principal off a second time.
4. No additional collateral seizure occurs after the all-wallet waterfall.
   Its cash collateral is already included. Illiquid collateral is not valued
   or liquidated by this component. Interest remains the existing scheduled
   payment model; this checkpoint adds no daily accrued-interest claim.
5. Retain the strongest living social tie as the single residual beneficiary,
   with person ID breaking equal-weight ties. Without one, escheat separately
   to each currency's system government account. This is an explicit legacy
   heir rule, not the proposed family-based multi-heir policy.
6. Retain negative cash balances in the inventory as unresolved deficits. They
   neither provide spending power nor disappear into an unrelated wallet.
   Their legal priority and other shared obligations remain full-estate work.

Example: 100 USD checking plus 200 USD savings repays 300 of a 450 USD loan.
The bank records a 150 USD loss. An 80 CAD loan is paid from 100 CAD cash,
leaving 20 CAD for the heir. The 20 CAD cannot pay the USD shortfall.

## Canonical records and atomicity

| Table | Evidence |
|---|---|
| `cash_estates` | Deceased person, tick, beneficiary, fixed policy, expected inventory counts and completion event |
| `estate_cash_assets` | Source account, currency, opening balance, principal paid and residual distributed |
| `estate_loan_claims` | Loan, creditor, currency, accelerated principal, cash recovered, loss and charge-off transaction |
| `estate_cash_transfers` | Source/destination accounts, amount, purpose, loan reference and ledger transaction |

Every monetary change uses the ledger. Available prior wages arrive before the
inventory; remaining wage receivables pass through the existing claim-holder
history without creating cash. The complete death transition is one savepoint,
including wage collection, claim inheritance, cash settlement, existing share
handling, employment, guardianship and population effects. A failure in any
later part rolls the earlier settlement back. Repeated death cannot repeat it.

Invariants reconcile wallet totals to transfer receipts, principal to cash plus
write-off, recipient ownership/currency, and bank losses to exact ledger legs.
They validate the death-time snapshot, not a claim that a deceased account can
never receive a later payment. New records are authoritative in hash-contract-v6
and independently exported. An older contract cannot hide populated receipts.
Pre-19 replay permits only these named empty extension tables and their new
migration receipt; it does not rewrite or upgrade the recorded source.

## Validation and operation

`runs/estate-cash-rehearsal.yaml` extends the small provider-free daily-time
world. It disables checkpoints. It does not force a death or accelerate aging.
Use `tests/test_semantics19_estate_cash.py` for known-answer settlements,
cross-currency rejection, zero/partial/full repayment, claim/cash separation,
failure rollback, immutable evidence, migration rollback, exports and replay.
The replay test injects one deterministic mortality boundary in both executions;
this establishes replay behavior, not population mortality calibration.

Use a fresh short pytest directory and verify at least 40 GiB free beforehand.
No local full-suite campaign or paid provider calls are needed. Complete Python
coverage runs in CI shards. Validation results belong in the execution log.

## Remaining estate and succession specification

This closes a cash/credit accounting gap; it **does not close W5 or full estates**.
The next estate slice must inventory outstanding orders, escrow/refunds, legal
and IP claims, housing/project rights and shared commitments. Record whether
each is transferred, retained pending realization, rejected or extinguished.
Route late receipts through that declared policy rather than strand them in a
deceased wallet. Reconcile security quantities and creditor priority without
inventing an execution or price for illiquid assets.

Business succession must retain immutable founder/initiator history and add
effective ownership/stewardship intervals. Update actual action authority,
agent context, founder policy selection, labor capacity and construction/home
projections to use those intervals. A transferred share alone cannot transfer
control. Separate a minor's beneficial assets from a guardian's authority.
Historical views must resolve the owner/steward at the selected tick.

Acceptance must include owner death during a project, guardian/beneficiary
death, simultaneous migration, later refunds, multiple heirs, insufficient
assets, share conservation and exact replay. Cohort boundary fixtures and a true
multi-decade provider-free experiment still follow. W6–W9 remain open; goods
and equity price discovery retain equal research priority.

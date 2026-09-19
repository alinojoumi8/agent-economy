# Full estate assets and succession — W5 implementation in progress

This work extends the [cash checkpoint](2026-09-07-estate-cash-and-credit.md).
The intended Semantics-20 deliverable includes full estate inventory/disposition,
future receipts and effective business/property control. It does not replace the
remaining W5 cohort/multi-decade evidence or any W6–W9 work. Goods and equity
research retain equal priority.

## Current development state

The unpublished schema-25 migration and hash-contract-v7 are still being
developed. Do not treat this version as a completed estate implementation.
Frozen migrations through v024 and hash manifests through v6 remain unchanged.

The latest local steps implement the private household position reader,
per-currency cash inequality and a selected-tick local operator inspector. See
[the implemented reporting contract](#implemented-household-positions-and-cash-inequality).
The [financial inspector contract](2026-09-08-household-financial-inspector.md)
documents the city/People entry point, privacy boundaries and currency display.
The day-8,009 report and consent failures are repaired and revalidated using
isolated readers: 21 historical reports, seven partnerships, 16 negative audit
cases and 40 focused tests passed. The [repair and continuation boundary](2026-09-09-historical-role-reconstruction.md)
preserves the original native runtime and failures; root integration is pending.
The cohort audit separately verifies two native adults. A [bounded comparator](2026-09-09-campaign-replay-and-export.md#implementation-and-fixture-validation-in-isolation)
has passed isolated compatibility and resource probes; full replay/export and
the remaining estate acceptance are still open. Earlier sequencing notes below retain the
requirements that led to this implementation; they do not mean the reader is
still unimplemented.

`BusinessControl` separates immutable founder identity from the effective
operator. Shareholders retain beneficial assets; a minor's guardian can be the
temporary operator without acquiring the child's shares. After the guardian's
authority ends or the child reaches adulthood, the engine records a new interval.
If no adult shareholder or guardian is available, an existing employed manager
can continue operation; otherwise the record explicitly says vacant.

Actions, legal authority, construction, daily work, agent context/purpose,
workforce recovery, benefits, cognition sponsorship and tier/working counts use
the operating identity. Founding events, initial skill seeding and historical
founder identity retain their meaning. Selected-tick construction attribution
uses the interval applicable at that tick, not the current operator.

Inherited securities enter the existing `share_movements` history and an
immutable estate receipt. They do not create an execution, market price or new
issued shares. Whole securities use declared integer weights and largest
remainders, with beneficiary ID resolving ties. A distribution key allows later
receipts to have separate evidence. No-heir holdings pass to the system holder
rather than disappear; operating managers can keep the legal firm running.
Unfilled stock, FX and IPO bids from the deceased are cancelled.

The business regression passed 130 cases before the estate-case integration.
It exercised actual pricing authority and production, minor ownership versus
guardian operation, adult transition, repeated succession, no-heir manager
continuity, duplicate death and whole-death rollback. The estate-case integration
then passed 45 focused cases, including export, migration rollback, restart and
exact recorded replay. The subsequent combined regression passed 113 checks;
one construction-refund fixture failed before exercising the behavior. After
correcting its optional configuration and cancellation reason, its focused
rerun passed. Production code did not change between those runs.

## Implemented estate-case behavior under development

`EstateCases` adds immutable opening inventories, beneficiaries, creditor terms,
bank losses, realized-cash receipts and disbursements. It replaces the
Semantics-19 cash component only for Semantics 20. The opening event seals the
inventory; it does not declare retained rights or claims finally resolved.

The declared policy gives equal integer weights to living partners and children.
If neither exists, living parents share; otherwise the strongest living social
tie inherits, with ID breaking ties. Without a beneficiary the residual passes
to the same-currency system government. Every receipt and whole-share holding
uses largest remainders and stable beneficiary ID ordering. This is an explicit
research assumption, not a jurisdiction's inheritance rule.

Available cash first clears the deceased's other negative cash wallets in the
same currency, in account-ID order. All same-currency bank principal is then
accelerated in loan-ID order, followed by
uncontested personal payment/indemnity obligations and admitted legal awards in
stable source-ID order. Known monetary disputes can reserve actual remaining
cash before beneficiaries receive the residual, as described below. Heirs do
not become personal debtors. Unpaid bank principal closes in the
loan scheduler and is charged against bank equity; the estate retains a claim
against future receipts. Recovery credits reserves and reverses the prior
equity/loss entries once, before any residual inheritance. The underlying
reserves-funded banking model and absence of daily accrued interest are retained.

The ledger hook posts the original payment and consequent estate disbursements
inside one savepoint. Nested estate recipients use a queue, which is cleared on
success or rollback. Receipts preserve original transaction links and the cash
balance immediately after each incoming credit. This records which receipt
absorbed an existing negative wallet balance, even when several estate credits
queue before distribution. Different currencies cannot offset each other.

Unpaid wage receivables remain under the deceased's recorded nominee holder.
The estate's immutable beneficial interests govern later realized net cash;
claims do not become cash or get copied into each heir's balance. A later
beneficiary death routes subsequent payments through that person's own recorded
estate. Construction funding/refund authorship remains the original contributor's.

The inventory records personal securities, noncash accounts, wage claims,
construction projects and contribution refund rights, contract interests and
legal matters. Personal service commitments, insurance/compute entitlements,
pending job/loan applications, stock/FX/IPO bids and the deceased's own pending
family/migration requests receive explicit ending dispositions. Company assets,
cash, credit, IP and licences stay in the company when its shares are inherited.
Monetary legal matters now have the award, reserve and earned-wage paths below;
the remaining legal rights still need their full disposition. Personally
owned projects use the title and custody history described below.

The current development manifest has forty-three new authoritative tables, schema 25,
hash-contract-v7. Its inventory hash is
`f3a8f1f80977a876d474b70d12a0848e4622ee3d1b40f3eeac919426a8aaefe3`.
This manifest remains **unpublished and extensible** until the complete estate
deliverable below is ready; do not freeze it around the current focused tests.

## Implemented personal project and home succession

`ProjectRights` records beneficial interests in `project_interest_lots` and
effective authority in `project_stewardships`. Fractions are reduced exact
ratios stored as decimal strings, so repeated inheritance cannot round away a
property share or overflow SQLite integers. Every distribution references the
previous interest and the recorded estate weights. Current interests sum to
one at every historical boundary.

The original construction owner, initiator and funding contributors stay
unchanged. One successor can inherit several active projects while retaining
an existing project without colliding with the original-owner unique index.
The largest adult beneficial owner manages the project; otherwise a current
guardian may act for a minor owner. Guardians receive authority without title.
Custody changes refresh business and property authority immediately, including
when the former guardian remains alive. A vacant position stays explicit.

A successor can perform actual construction work and complete the inherited
home. Refunds return to the recorded funding accounts and flow through any
deceased contributor's estate. Unclaimed unfinished projects cancel and refund
their contributors; completed unclaimed homes retain system title and never
become random residential districts. Household residence resolves current
beneficial rights in the resident's actual region. Inheritance does not move a
person or make a remote property into a home in their destination region.

The city and People views show current owners with exact fractions, the
manager's capacity and the original owner at the selected tick. Earlier
construction milestones remain associated with their owner at that time.
Exact home identity requires public visibility for the original owner, all
current beneficiaries and the current manager. Withheld homes also disappear
from map places, exact presence, agent coordinates and residence projects;
requesting only an agents layer cannot recover the location. Projection reads
leave authoritative state unchanged.

The focused regression passed **73 tests in 135.78 s**, covering the new
property cases, estate cases, business succession, Semantics-13 construction
and schema/hash foundations. It includes source-preserving recorded replay
and restart from an explicitly seeded, funded project at tick zero, followed
by death in the real nightly phase. That fixture tests mechanics and replay;
it is not evidence of independently emergent house construction. The earlier
property run passed 12 cases and failed one migration fixture at the existing
unemployed-citizen gate; the successful combined run uses an eligible citizen.

Dashboard tests passed **258**; type, license and production-build checks
passed. The desktop/mobile browser test passed with shared owners, guardian
authority and navigation to an heir while retaining the selected tick. The
ownership text wraps in the city facts panel. Browser data is synthetic;
backend/API tests separately exercise actual inherited projects and privacy.

Logs: `tmp/project-rights-replay-regression.log`,
`tmp/project-rights-dashboard-tests.log` and
`tmp/project-rights-dashboard-build-final.log`. Browser artifacts are under
`tmp/project-rights-browser-739ad061/`. The backend run began with 94.39 GiB free
and used `C:/Users/matri/.codex/tmp/ae-765d4140`. These are focused local results,
not full Semantics-20 CI or a completed estate validation claim.

The follow-up documentation, world-workspace and Living Agents regression
passed **40 tests in 3.63 s**, including the existing historical map and privacy
contracts. Log: `tmp/project-rights-observer-regression-final.log`; fresh test
base: `C:/Users/matri/.codex/tmp/ae-551381e8`, starting with 94.09 GiB free.

## Recorded monetary awards and disputed estate cash

`LegalAwards` records actual monetary decisions and accepted settlements. For
linked contractual payment/indemnity obligations, the amount means the total
adjudicated entitlement: earlier cash collections count toward it. Explicit
obligation IDs or admitted obligation evidence identify the debt being replaced.
Unrelated additional damages require an explicit declaration. The old unpaid
contract claim is released, the obligation becomes adjudicated and cannot be
collected again, and the award retains its unpaid remainder. Prior collections
above the adjudicated total are recorded without inventing a clawback.

Both awards existing at death and later awards enter the same estate creditor
queue. Later admissions record the tick and receipt frontier without rewriting
the opening inventory, its claim count, or earlier distributions. Contract
termination and expiry release cancelled pending claims. A living respondent
pays only available same-currency cash at enforcement; unpaid awards remain
recorded. Ordinary cash awards do not yet have a general collection scheduler.
The compensation and firm-bankruptcy paths below collect earned-wage awards
and record losses on other outstanding firm awards.

`EstateDisputes` protects known contested monetary obligations and holds only
cash actually received, up to the requested amount less prior collections.
Admitted creditors are paid before remaining cash funds disputes; beneficiaries
receive the residual. Separate escrow accounts create no money. Final decisions,
dismissals and accepted settlements release held funds through the deceased's
wallet and the ordinary estate waterfall. Later-filed claims affect future
receipts and do not claw back a survivor's earlier inheritance. Multiple
disputes can retain distinct reserves in stable admission order.

Award issuance, underlying-claim release, reserve resolution and resulting cash
transfers share the estate transaction boundary. Rollback restores the original
incoming credit as well as downstream collections. Reconciliation checks both
award settlement legs and the reserve release's matching later estate receipt;
cash cannot be redirected to a third party or currency. These additions use eight
award journals and three dispute journals in the unpublished v7 export/hash and
replay inventory. Frozen migrations through v024 and manifests through v6 are
unchanged.

The Politics & Law workspace and current `/api/v2/legal` projection now expose
actual award payments separately from earlier credited payments. Historical
views reconstruct collected, outstanding, held and released amounts at the
selected tick; the original enforcement result remains an admission snapshot.
Adjudicated contractual obligations also retain their earlier historical status.
The new monetary projection omits filing bodies, private metadata, wallets and
heirs. Financial details require both personal parties to be core/pinned at the
selected tick. This does not claim a complete audit of all older legal payloads.
The responsive readout keeps every amount visible on desktop and mobile.

The integrated regression passed **162 tests in 330.66 s**. It covers all six
Semantics-20 test modules, Semantics-19 cash estates, Semantics-18 earned wages,
Semantics-13 construction, schema/hash foundations and the existing legal suite.
It includes live API reads, partial collection, historical/private projections,
multiple disputes, currency isolation, deceased claimants, injected rollback,
export, restart and exact recorded replay with an unchanged source database.
Log: `tmp/estate-legal-integrated-regression.log`; fresh base:
`C:/Users/matri/.codex/tmp/ae-7ef29381`; initial free space: 93.81 GiB.

Earlier focused runs passed 41 and 46 checks before the subsequent hardening,
then 16 checks in 72.38 s and 36 in 79.22 s. The new replay fixture initially
failed twice because its court role was peripheral and institutional decision
routing was disabled. The corrected scenario pins the regulator and enables
that routing at genesis in both source and replay. A seeded pending dispute,
real nightly death, restart and the normally scheduled regulator then exercise
collection; this is a mechanics fixture, not evidence of emergent adjudication.

Dashboard tests passed **259** and type/license checks passed. The desktop/mobile
browser check passed; visual inspection led to replacing a horizontally clipped
mobile table with a responsive financial readout, whose browser rerun also
passed. Artifacts: `tmp/legal-relief-browser-f82e1b19/`; logs:
`tmp/estate-legal-dashboard-tests.log`, `tmp/estate-legal-browser-responsive.log`.
The production bundle was regenerated successfully after backend testing;
`tmp/estate-legal-dashboard-build.log` retains the existing large-chunk warning.
These are focused local results, not full CI or a completed Semantics-20 claim.

The final documentation and existing observer regression passed **40 tests in
3.27 s** (`test_documentation.py`, `test_world_os_workspace_projections.py`,
`test_living_agents_projection.py`). Log: `tmp/estate-legal-docs-and-observers.log`;
fresh base: `C:/Users/matri/.codex/tmp/ae-69f4b510`; initial free space: 93.42 GiB.

## Wage judgments and actual compensation — 2026-09-08

`WageAwards` now connects legal decisions and accepted settlements to recorded
earned work. A filing fixes a gross earnings interval with an actual claim and
accrual cutoff. Earlier adjudicated intervals cannot be claimed again; pending
overlaps, different parties, currency mismatches and future work are rejected.
Later work retains its own collectible amount. Scripted claim offers carry
the actual interval and suppress duplicate pending claims.

The judgment is total gross compensation for that interval. Actual earlier
payroll credits it once. A recorded bankruptcy discharge is a separate prior
loss credit, not another payment or another bad-debt loss. An immutable novation
journal removes the original remaining receivable/payable and records the
replacement compensation accounts. It does not increase the original wage
claim's write-off counter. Additional non-wage damages require a separate
matter. Prior payments exceeding the award do not trigger an automatic clawback.

Collections use actual same-currency employer cash. Each payment reconciles
gross compensation, current tax withholding and net cash. Net receipts after
the worker's death enter the recorded nominee estate and its existing waterfall.
At firm bankruptcy, existing bank priority is retained, followed by wage awards,
other earned wages and other cash awards. Remaining award losses release only
recorded noncash rights; later deposits cannot resurrect discharged compensation.
This is a declared simulation policy, not a jurisdiction's insolvency or tax rule.

The selected-day legal projection and responsive dashboard distinguish gross
pay, tax, net receipts, unpaid compensation and current/prior losses. Research
`labor_income` includes only new gross wage-award collections at the payment tick;
earlier payroll is already counted, and novation, write-off and inheritance are
not counted again. GDP remains based on actual goods sales. The existing nominal
aggregate across currencies is retained; this change does not create an FX
valuation or solve the beneficial-interest wealth boundary below.

Four added journals (`legal_wage_scopes`, `legal_wage_awards`,
`wage_claim_novations`, `legal_award_losses`) join the unpublished v7 inventory.
Payment tax and earlier discharge credits are also explicit. Frozen v024/v6 and
earlier migrations/manifests remain unchanged.

The combined estate regression completed **178 passing tests and one failing
test assertion in 380.23 s**. The failure incorrectly expected a rejected
currency judgment to leave no audit event. The corrected test verifies that
every other hashed table remains identical, one validation-failure event is
recorded, and subsequent EUR compensation leaves domestic USD cash untouched.
With production source unchanged, the complete wage suite then passed
**17 tests in 45.43 s**. It also covers accepted settlement, partial prior pay,
continued work, successive periods, 100% withholding, bankruptcy before and
after judgment, rollback, export, death, restart and exact recorded replay.

The replay fixture initially collected no new award cash because ordinary
payroll had already fulfilled the requested amount. Its revised declared
genesis arrears remain partially unpaid at adjudication; ordinary goods sales
fund later compensation after a real nightly death. Source and replay use the
same genesis setup and scheduled regulator, and the source file's hash remains
unchanged. This is mechanics evidence, not emergent wage bargaining or calibration.

Backend logs: `tmp/wage-awards-full-estate-regression.log` (base
`C:/Users/matri/.codex/tmp/ae-5650d6b8`, initial free space 93.28 GiB) and
`tmp/wage-awards-final.log` (base `C:/Users/matri/.codex/tmp/ae-28a5781c`,
initial free space 92.85 GiB). Dashboard unit tests passed **259**; type and
license checks passed. The desktop/mobile browser check passed in 6.4 s and
both widths were visually inspected. Artifacts:
`tmp/wage-awards-browser-fa9f1d9a/`; logs:
`tmp/wage-awards-dashboard-tests-final.log`, `tmp/wage-awards-browser.log`,
`tmp/wage-awards-dashboard-typecheck.log`, `tmp/wage-awards-dashboard-licenses.log`.
The production dashboard bundle was rebuilt successfully after backend testing
(`tmp/wage-awards-dashboard-build.log`); the existing large-chunk warning remains.
These results do not replace full CI or complete the estate deliverable.

The follow-up documentation and existing observer regression passed **40 tests
in 3.37 s**. Log: `tmp/wage-awards-docs-and-observers.log`; fresh base
`C:/Users/matri/.codex/tmp/ae-8eb84049`, initial free space 92.80 GiB.

## Shared consent and personal civic authority — 2026-09-08

Opening inventory now includes pending or agreed family requests when the
deceased is a household member or guardian in the consent snapshot, even when
another person proposed the request. The normal family cancellation path records
`person_died` without rewriting the original assents. An agreed move cannot later
relocate the survivors on the obsolete shared snapshot. A set-based invariant
also rejects a pending request that still names an estate's deceased participant.

`CivicAuthority` closes personal legislative office, agency leadership and open
legal representation inside the same death transaction. The inventory preserves
the original office and committee assignments; past bills, votes, party records,
agency capacity and the client's legal matter remain intact. Heirs do not gain
an office or a lawyer's authority. Living clients can continue their own matters.
The liveness authorization change is gated to Semantics 20.

The unpublished v025 migration replaces the legislative seat constraint with
uniqueness for active occupants only. Successive deceased officeholders retain
their distinct IDs, so another former holder no longer conflicts with an older
inactive row. Copy migration preserves all earlier legislative evidence and the
source database; frozen migrations through v024 remain unchanged. The v7 column
inventory hash is unchanged by this constraint update.

The broad regression passed **227 tests in 462.85 s**, including all eight current
estate modules, household consent, prior semantics, political and legal behavior,
schema/hash checks and older recorded replay. Log:
`tmp/personal-authority-estate-regression.log`; fresh base:
`C:/Users/matri/.codex/tmp/ae-73ae9099`; initial free space: 103.42 GiB.
The suite retains one upstream FastAPI/Starlette test-client deprecation warning.
The new full-world fixture uses normal nightly deaths of an affected household
member, legislator, agency director and counsel. A restart between days and exact
recorded replay preserve the source database's hash. These are declared genesis
mechanics fixtures, not evidence of emergent election or legal representation.

Earlier focused fixture failures exposed composite assent keys, the omitted
nightly age phase and a missing explicit counsel parameter. The first world
fixture also attempted an invalid day-zero birth; it now starts with a declared
shared adult household. Actual positive-day child death remains separately
covered. The corrected focused runs passed 13 checks in 23.77 s and the world
replay in 3.33 s before the successful broad run.

Subsequent inspection found that the organization timeline read the current
agency director after death. It now restores only the public director ID from
the recorded pre-death inventory for earlier days. No estate snapshot, heir or
future death field is included. API regression for before, at and after two
directors' deaths passed, including unchanged authoritative hashes after reads.
The follow-up personal-authority, documentation and existing observer regression
passed **54 tests in 29.91 s**. Log:
`tmp/personal-authority-history-and-observers.log`; fresh base:
`C:/Users/matri/.codex/tmp/ae-8cd9db90`; initial free space: 102.35 GiB.
This does not add appointment history
or claim complete historical reconstruction of policy-driven agency capacity.
The politics/law historical workspace does not expose current legislators or
counsel assignments. Existing city processing already releases deceased clerks,
reassigns their tasks and closes deceased applicants' pending cases; its death
inventory and end-to-end succession coverage still need to be completed.

Vacancy filling, new counsel appointments, remaining institutional authority and
the other estate liabilities below are still open. Semantics 20 remains
unpublished and extensible.

## City work, vacancies and permit rights — 2026-09-08

The death transaction now inventories five additional personal bindings:
`agency_staff`, `institutional_assignment`, `civic_application`,
`civic_appointment` and `civic_authorization`. All opening rows are captured
before either the case or assignment changes. Common city processors close the
staff interval, release unfinished assignments, abandon the deceased applicant's
pending case, cancel their appointment/occupancy reservation and revoke an unused
permit. The institutional task itself survives a worker's death. Its original
case, priority, deadline, application and fee evidence remain intact; a successor
can complete that same task. Original assignments remain in the estate record.

Fees are not refunded or charged again. A consumed permit remains the historical
incorporation record. The resulting company and its accounts survive the
founder's death and follow the separate business-control succession policy.
Heirs receive no personal permit or inherited clerk authority. Same-day clerk
and applicant deaths do not revive the cancelled case, in either tested order.
Whole-death rollback restores the inventory, cash, case and assignment together
when either the staff or applicant closing processor fails.

After genesis, Semantics-20 clerk succession selects an existing local adult in
stable agent-ID order. The person must be a citizen without another role,
retirement, current employment or operating authority over a live firm. The
initial permit offices retain their declared genesis staff. A later vacancy
does not create another adult or an external cash endowment; without a candidate,
the office remains unstaffed and its work stays pending until one is available.
This remains a declared staffing policy, not an application/consent/election or
public-sector compensation model. Older semantics retain their original fallback.

The organization workspace and city agency detail now share the same public
director-history reconstruction. Staff intervals and aggregate queue depth
retain the selected-day boundary. This does not reconstruct every older
policy-driven capacity change or add director appointment history.

The focused city suite passed **15 tests in 34.74 s**, covering real appointment
attendance/time allocation, task reassignment and completion, empty staffing
queues, later candidate availability, fees, personal permit revocation, actual
incorporation, same-day deaths, injected rollback and rejected dead authority.
The full-world scenario uses normal nightly deaths and scheduled agent actions;
it reopens the world between three days and verifies exact recorded replay with
an unchanged source database. Genesis declares an existing adult unemployed;
this is a mechanics fixture, not evidence of emergent labor supply or hiring.
Log: `tmp/civic-succession-final-focused.log`; fresh base:
`C:/Users/matri/.codex/tmp/ae-e5ee289e`; initial free space: 101.53 GiB.
The separate world replay passed **1 test in 3.73 s**
(`tmp/civic-succession-world-replay.log`, base `ae-5a8cf4d4`).

Earlier fixture corrections supplied the actual daily time reservation and the
ledger's `txn_id` key. A subsequent run passed 33 checks with one expectation
failure because no eligible replacement adult existed. Another passed 24 checks
with a world-fixture failure: adding a person after the initial census broke the
population identity. The final fixture preserves the recorded population and
declares existing labor availability at genesis instead. The production census
invariant was retained. Logs: `tmp/civic-succession-first.log`,
`tmp/civic-succession-focused.log`, `tmp/civic-succession-revised.log`.

The integrated regression passed **293 tests in 543.98 s**, covering all nine
Semantics-20 modules, Semantics 19/18/17/13/12, schema/hash foundations, existing
legal/political behavior, recorded replay, documentation and observer projections.
Log: `tmp/civic-succession-integrated-regression.log`; fresh base:
`C:/Users/matri/.codex/tmp/ae-ed65a5e4`; initial free space: 101.44 GiB.
One upstream FastAPI/Starlette test-client deprecation warning remains. No schema
or hash-inventory extension was needed for the additional inventory kinds.
These are bounded local checks, not full CI or completion of the estate model.
Semantics 20 remains unpublished.

## Job negotiations and nominated permit counsel — 2026-09-08

Estate opening now withdraws both pending and negotiating applications for a
deceased candidate and expires that candidate's pending job offers. The opening
inventory preserves the original application and offer; superseded offers and
the firm's open job remain intact. Another living candidate can apply and accept
the same vacancy. A surviving company's offer is retained when its former
representative dies: the candidate can still accept the company's quote, and
the firm's current operator can accept a candidate's counteroffer. Actual actor
contexts expose those offers to the appropriate surviving party. Invariants
reject reactivated negotiations or pending offers belonging to a dead candidate.

A pending permit case that depends on a deceased nominated lawyer now ends in
the same death transaction, including its appointments and institutional tasks.
An unused authorization depending on that lawyer is revoked with a recorded
reason. Original case payloads, paid-fee ledger legs, approved case evidence and
consumed authorizations remain intact. An incorporated company survives its
former permit lawyer. Heirs acquire neither counsel authority nor the permit.

The applicant can submit a fresh application with qualified living counsel and
the same proposed name after the unused authorization is revoked. This follows
the normal application and fee process; it does not amend the old record or
refund the original fee. Active and consumed authorizations still reserve the
name, and an existing firm's name remains protected. Semantics-20 discretionary
approval rechecks mechanical eligibility. Normal finalization also rechecks
under-review cases, denying an invalid case and ending its pending task. The
older Semantics-12 approval behavior remains gated and tested unchanged.

Injected failures after job-right closing, case abandonment and permit
revocation roll back the entire death transaction. The three-day full-world
scenario exercises a candidate's death, later counsel death, normal queued
actions, reopening between days and exact recorded replay with an unchanged
source database. These are declared provider-free mechanics scenarios, not
evidence of emergent hiring or legal-service supply.

The first personal-commitment/city checks passed **28 tests in 50.36 s**
(`tmp/personal-commitments-first.log`, base `ae-7984ef9a`, initial free space
100.35 GiB). The expanded replay/legacy checks passed **27 tests in 47.02 s**
(`tmp/personal-commitments-replay-and-legacy.log`, base `ae-8b76c1df`, initial
free space 100.23 GiB). After adding actual actor-context and active/consumed-name
protection assertions, the final focused run passed **33 tests in 34.24 s**:

```powershell
.\.venv\Scripts\python.exe -u -m pytest -q tests/test_semantics20_personal_commitments.py tests/test_labor_ipo.py --maxfail=2 --basetemp C:/Users/matri/.codex/tmp/ae-20d76e9b
```

Log: `tmp/personal-commitments-final-focused.log`; initial free space 99.98 GiB.
One upstream FastAPI/Starlette test-client deprecation warning remains. No UI,
schema or hash-inventory change was needed for these additional inventory kinds.
The integrated regression then passed **326 tests in 577.05 s**, covering all ten
Semantics-20 modules, the existing labor/IPO suite, Semantics 19/18/17/13/12,
schema/hash foundations, legacy legal/political behavior, recorded replay,
documentation and observer projections. Log:
`tmp/personal-commitments-integrated-regression.log`; fresh base:
`C:/Users/matri/.codex/tmp/ae-f9fdd3c6`; initial free space 99.56 GiB, followed by
98.56 GiB at completion. The same upstream test-client warning remains. These
bounded local results do not replace full CI or complete W5; Semantics 20 remains
unpublished and extensible.

The following read-only inspection scoped the service tests implemented below:

- Insurance collection already skips cancelled policies and checks that the
  insured person is alive. Nightly premiums precede mortality, so preserve a
  valid charge made before death while proving later premiums cannot be taken.
  Exercise a real purchase, cancellation evidence, the later premium processor,
  and the distinct case where the insurer's operator dies but its company lives.
- Compute activation follows lifecycle settlement. Death opening already
  cancels the person's pending/active subscriptions; government renewal and
  employer selection already require living recipients. Exercise actual
  purchased and sponsored plans across activation and expiry, retaining the
  original payment evidence and living workers' access after payer-firm
  succession. Do not create a refund or transfer a personal entitlement merely
  because cancellation occurs. The public action dispatcher rejects dead actors;
  direct internal helpers alone are not a substitute for that action-path test.
- Personal pending loan applications already expire at estate opening, and loan
  approval rejects non-pending applications. The existing case only inserts an
  application directly. Add actual application and officer-decision coverage,
  including a firm's application surviving its representative. Due loan payments
  precede mortality in the nightly order; do not rewrite an earlier valid payment.

Use rollback, invariant rejection and restart/replay evidence for the remaining
paths. Source inspection alone does not establish that these service commitments
are finished, and it does not resolve nominee reporting or other liabilities.

## Insurance, compute and credit commitments — 2026-09-08

The actual purchase, sponsorship and underwriting paths now have death and
succession coverage. Insurance ends for a deceased insured person without later
premiums or an inherited policy. A valid premium collected before mortality in
the same nightly cycle remains paid. The surviving insurer continues collecting
premiums and paying medical claims after its former operator dies.

Purchased, employer-sponsored and government-sponsored compute access ends for
the deceased recipient, including pending activation and later expiry. Original
payments remain recorded without an invented cancellation refund. Living
employees retain company-funded access when only the firm's operator dies, and
the successor can pay for renewal through the actual sponsorship action.

Personal pending loan applications expire at death and reject later officer
approval. The heir can make a new application in their own identity. A company's
pending application survives its representative, can be approved normally and
services its own loan without charging the successor's personal account. An
actual principal payment before death remains recorded; the estate settles the
remaining principal and the closed loan cannot collect another installment.

Estate reconciliation now rejects active insurance, active/pending compute and
pending personal loan applications belonging to an estate's deceased person.
It also checks closed service records against their opening inventory, preserving
the original identity and recorded terms while allowing future additive metadata.
Changing a closed record to another holder does not transfer the entitlement.
Injected late failures restore all affected records and ledger history, and a
subsequent retry can settle the same death successfully.

The full-world scenario purchases insurance and compute and obtains an approved
loan through actual actions at declared genesis. It uses existing adults and
existing cash; an initial insurer is supplied if the profile lacks one. It does
not alter the census or claim emergent insurance supply. Normal nightly mortality
then collects the due premium, closes the person's services and settles the loan.
Three days with reopening between days reproduce exact recorded replay, and the
source database remains byte-for-byte unchanged.

Initial service checks passed **20 tests in 19.06 s**
(`tmp/service-commitments-first.log`, base `ae-be180884`, initial free space
98.47 GiB). The expanded world/legacy run passed **51 tests in 74.19 s**, including
the existing Semantics-11 cognition and P1 health/credit behavior:
`tmp/service-commitments-replay-and-legacy.log`, base `ae-93fe44ec`, initial free
space 98.35 GiB. After adding holder/terms reconciliation, the service suite
passed **27 tests in 28.10 s**:

```powershell
.\.venv\Scripts\python.exe -u -m pytest -q tests/test_semantics20_service_commitments.py --maxfail=2 --basetemp C:/Users/matri/.codex/tmp/ae-8339c64d
```

Log: `tmp/service-commitments-final-focused.log`; initial free space 98.13 GiB.
One upstream FastAPI/Starlette test-client deprecation warning remains. These
focused results do not complete W5. No
schema, hash-inventory or UI change was needed for this service increment.

The integrated regression subsequently passed **383 tests in 1248.15 s**, covering
all eleven Semantics-20 modules, Semantics 19/18/17/13/12/11, schema/hash
foundations, existing labor/IPO and P1 health/credit behavior, legal/political
behavior, recorded replay, documentation and observer projections. Log:
`tmp/service-commitments-integrated-regression.log`; fresh base:
`C:/Users/matri/.codex/tmp/ae-6fa4d5cd`; initial free space 98.02 GiB, with 88.46 GiB
remaining after completion. The upstream test-client warning remains. This run
took longer than the preceding batch; approximate fixture creation-time gaps
also widened for existing export/history cases, but the cause was not isolated.
These local checks do not replace full CI or establish completion of W5.

Read-only liability inspection identified the cash-deficit case below. `Ledger._post`
and `Ledger.transfer` preserve the journal and currency totals but permit a
negative account balance; `Ledger.reconcile` checks those totals and materialized
balances, not nonnegative cash. Existing estate tests deliberately exercise a
negative wallet and later credits. `_receive` correctly absorbs the receiving
wallet's own deficit before releasing available cash. Before the following
increment, `open` recorded other negative wallets separately and processed
positive wallets individually.

The acceptance plan began with checking of -50 and savings of +100 in one
currency: record the transfer that clears the deficit before distributing the
remaining 50, preserving each opening balance and its original ledger evidence.
It extended to multiple banks and deficient wallets, late receipts, receipt
ordering, creditor priority, no-heir estates and a deceased beneficiary's later
estate. The implementation and results follow.

## Same-currency estate cash deficits — 2026-09-08

The -50 checking/+100 savings baseline reproduced the defect: the beneficiary
received 100 while the checking deficit remained. The declared estate policy is
now `family_equal_deficit_then_bank_then_contract_v1`. Before paying creditors,
reserving disputed cash or distributing a residual, an available receipt clears
other negative checking, savings and FX wallets belonging to the same deceased
person and currency, in account-ID order. The example now transfers 50 to
checking and distributes only the remaining 50. Currency conversion, a new loan
contract and a new interest-accrual regime are outside this increment.

`estate_cash_offsets` records the source receipt, destination wallet, negative
balance before the offset, amount and ledger transaction. Rows cannot be updated
or deleted. The source receipt still records the incoming credit and its immediate
post-credit balance; the opening inventory also stays unchanged. A negative
opening item is historical evidence, not a claim that a subsequently cleared
wallet is still negative. Current settlement comes from the ledger and offsets.

The credit into the negative wallet also produces a linked receipt with zero
available cash. It is an internal estate transfer, not new external income or a
second deficit claim. Reconciliation requires offsets plus disbursements to equal
each receipt's available cash, checks exact ledger and cross-bank reserve legs,
and reconstructs balances immediately before the first allocation. That boundary
includes credits already posted while estate processing is queued. Deficits must
be cleared before any creditor or heir payment. Whole-death and initiating-credit
failures roll back the original payment, offsets and downstream distributions.

Focused coverage includes insufficient cash, multiple wallets and banks, queued
credits, separate currencies, no-heir estates, bank principal/write-off recovery,
late receipts, a deceased beneficiary's own deficit, immutable evidence and
corruption rejection. Semantics 19 retains its old recorded behavior. The new
table is included in schema verification, canonical hashing, export and replay;
the unpublished schema-25/hash-v7 manifest remains extensible.

The initial defect test failed as expected (`tmp/cash-offsets-baseline.log`,
1 failure in 3.46 s). The first implementation run passed 25 tests in 142.42 s
including the existing estate-case suite (`tmp/cash-offsets-first.log`); the
expanded focused run passed 25 tests in 44.00 s
(`tmp/cash-offsets-expanded.log`). The first world/generations run passed 26
tests and failed one fixture assumption: the seeded adult already had a savings
account, which correctly supplied the first offset. The fixture now funds that
existing wallet rather than assuming its newly created wallet would be first.
No production behavior changed to accommodate this failure.

The corrected focused run passed **27 tests in 35.28 s**, including three normal
world days with reopening, exact recorded replay and an unchanged source database:

```powershell
.\.venv\Scripts\python.exe -u -m pytest -q tests/test_semantics20_cash_offsets.py --maxfail=2 --basetemp C:/Users/matri/.codex/tmp/ae-f97d40ce
```

Log: `tmp/cash-offsets-corrected-world.log`; initial free space 80.38 GiB, followed
by 80.29 GiB. One upstream FastAPI/Starlette test-client deprecation warning
remains. The world fixture uses an existing adult and cash with a declared ledger
deficit; it does not establish a new public overdraft facility. Drive free space
varied substantially between batches; these observations do not identify the
cause. No cleanup or unrelated process stop was performed.

The broader regression passed **262 tests in 781.79 s**, covering all twelve
current Semantics-20 modules, Semantics-19 cash estates, schema/hash foundations,
recorded replay, research export and documentation. Log:
`tmp/cash-offsets-estates-and-contracts.log`; fresh base:
`C:/Users/matri/.codex/tmp/ae-27c6f144`; initial free space 80.27 GiB, with 85.91 GiB
measured afterward. Its dedicated test files totaled 0.613 GiB. The command is
recorded in the execution log. The upstream test-client warning remains. No
source, documentation, build, staging or commit mutation occurred during the
scientific run. This is bounded local validation, not full CI or completion of W5.

After updating the plan, the existing exchange and documentation suites passed
**25 tests in 1.07 s** with no warnings. Log:
`tmp/cash-offsets-exchange-and-documentation.log`; fresh base:
`C:/Users/matri/.codex/tmp/ae-396f5e02`; initial free space 85.89 GiB. The exchange
checks cover rejection of a sale by a non-owner, actual price/time matching and
partial fills, and the absence of an engine-invented price without orders.

The original [S8 specification](2026-09-06-research-city-specs.md#s8-banking-financing-and-market-depth)
explicitly defers short selling, leverage, derivatives and external execution.
The exchange already bounds a sale by shares held and rechecks affordability at
matching. Verify that ownership contract and keep unsupported negative holdings
distinct from an implemented short position. Do not expand W5 into the deferred
instruments. Follow the cash-deficit work with the per-currency nominee/beneficial
reporting described below, retaining face-value claims separately from cash and
counting each underlying claim once.

## Implemented estate securities custody and settlement

The proposed funded-sale defect was reproduced: after an actual 200-cent sale,
the deceased owner's 100-cent bank loss remained unpaid. `EstateSecurities`
now applies the declared `known_claims_then_residual_v1` policy under Semantics
20. Personal securities stay in the deceased nominee's holdings while their
currency has an unpaid known estate claim, a cash deficit or an underfunded
legal reserve. Solvent holdings retain the existing in-kind inheritance path.
The opening security inventory records retained custody; later lot, sale and
release evidence identifies the actual disposition.

The existing `place_order` action accepts an `estate_id` sale scope supplied in
the authorized actor's private decision context. A living adult beneficiary,
or a current guardian for a minor beneficiary, can represent the estate.
Recorded beneficial paths can traverse a beneficiary's subsequent estate.
The quote records the living actor, nominee, beneficiary, guardian when
applicable, ages, beneficial path, estate frontier and settlement account.
The representative receives authority without receiving the pool as personal
shares or assuming its debts. Unrelated actors and estate purchases are rejected.

Matching rechecks current authority, available units, actual buyer cash and
currency. The instrument's currency determines the estate settlement wallet;
it need not be the representative's home currency. A fill posts the buyer's
payment, share movements, trade/order changes, custody allocations and estate
waterfall inside one savepoint and receipt batch. The 200-cent acceptance sale
now reverses 100 cents of bank loss and pays 100 cents of residual inheritance.
No price is invented for a book that cannot execute.

Partial fills retain the unsold units while claims remain. Once known claims
and reserves are satisfied, unsold securities pass in kind using the existing
whole-unit distribution rule. Releases carry transaction, receipt, claim,
claim-release, reserve and resolution frontiers, allowing reconciliation to
check creditor priority at release. Replacing a disputed contract with a legal
award defers release until both operations and their cash movements finish.
A zero-cash dismissal can release securities without manufacturing a sale.

Guardian loss, adulthood and a representative's death invalidate old quotes.
Late in-kind inheritance received by a deceased beneficiary enters that
beneficiary's estate, where its own creditors precede the next beneficiaries.
If no ordinary adult shareholder operates the company, an eligible estate
representative can do so in recorded `estate` capacity. Selection between
estate pools uses remaining units after sales, then estate ID; representative
selection uses the recorded beneficial weights and stable identity ordering.

Five immutable tables extend the still-unpublished schema and hash inventory:
`estate_security_lots`, `estate_security_releases`, `estate_security_orders`,
`estate_security_sales` and `estate_security_sale_lots`. Export and exact replay
include all five. Authority reconciliation rejects a frontier that predates
its own estate or refers to a future death.

### Restart and decision provenance

The recorded-decision acceptance case exposed two additional defects.
`World.initialize` used to recalculate the last completed day's city occupancy
when reopening a run, applying later business ownership to earlier activity.
Semantics 20 now resumes the committed city and lets the next tick update it;
the test compares the authoritative hash before and after each reopening.
Earlier semantics retain their historical initialization behavior.

Replay provenance also still identified operators by immutable founder ID.
It now reconstructs Semantics-20 operating intervals. These intervals record
days, so a transition day can admit either adjacent operator's decision purpose;
this does not authorize an action after current authority has ended. A recorded
decision must cite its own recorded purpose even on that boundary day.
Bankruptcy still precedes the same day's decisions and excludes founder routing.
Operational purposes and unrelated actors remain invalid references.

### Validation through September 8

The funded-sale baseline failed as expected in
`tmp/estate-securities-baseline-corrected.log`. Initial custody integration passed
30 tests, and its expanded failure/custody set passed 14. The first full-world
fixture needed birth-date and foreign-account corrections; subsequent failures
exposed the city-resume and operator-provenance defects above. After those fixes,
20 tests passed in 114.84 s (`tmp/estate-securities-provenance-and-cascade.log`).
Five additional dispute, deficit and affordability cases passed in 10.90 s;
the affordability fixture was corrected to spend cash after an initially funded
order was accepted. A separate remaining-unit stewardship case passed in 1.38 s.

The broader regression passed **296 tests in 1011.21 s**: all thirteen
Semantics-20 modules, Semantics 19 and 8, recorded-replay golden cases, research
export, exchange, documentation and five provenance cases. Log:
`tmp/estate-securities-integrated-regression.log`; fresh base:
`C:/Users/matri/.codex/tmp/ae-a8aaeed8`. Initial free space was 80.04 GiB;
78.57 GiB remained afterward, and this batch's artifacts occupied 0.721 GiB.

After the final authority-frontier and exact-purpose checks, the complete
28-case securities module plus the five existing provenance cases passed
**33 tests in 160.42 s**. Log:
`tmp/estate-securities-final-authority-history.log`; fresh base:
`C:/Users/matri/.codex/tmp/ae-e27072ef`; initial free space 78.48 GiB.
A read-only audit of the prior batch found no violations of those two new
predicates among 1,580 recorded decision references and 20 security authorities.
Five operator-workspace or invalid-JSON fixtures did not support that audit;
the audit is a compatibility check, not a replacement for their tests.
The focused and broader runs emitted the existing Starlette/httpx deprecation
warning. No source, documentation, build, staging or commit changes occurred
while scientific tests ran.

The source/restart/export/replay case uses three actual world ticks and
prescribed decisions through the recorded gateway. It proves the accounting
and replay path, not autonomous selling or an empirical price result. The
guardian/adulthood case advances eligibility to a birthday; it is not the
required multi-decade cohort campaign. Default scripted agent policies do not
yet choose estate orders; the private context makes the action available to
policies and future experiments. Goods and equities remain equally primary.

## Implemented project creditor custody and late inheritance

`EstateProperty` now retains a personal project's exact title fractions under
the deceased nominee when its escrow-account currency has unsettled known
creditors, cash deficits or underfunded legal reserves. The initial completed
home test reproduced unencumbered inheritance while a bank loss was unpaid.
The fix keeps that title in custody until settlement. Construction cost is not
a market valuation, and custody creates no execution or liquidation proceeds.

`EstateAssetCustody` shares the existing creditor-frontier and representative
rules between securities and property. A living adult beneficiary or a current
guardian can administer a retained project. A household containing a residual
beneficiary can use its completed home; the guardian's authority does not confer
title. Guardian loss now uses the recorded public-administration policy below,
or leaves a vacancy when no eligible official exists, while preserving the
child's rights and residence. A recorded adult transition can
restore authority. Representative selection sums an adult beneficiary's interests
across all inherited branches before ranking them, while each authority retains
its own recorded path. This fixes a reproduced case in which two one-third
routes lost management priority to another person's single third.

An actual later cash receipt settles the existing waterfall and releases title
in kind. If a beneficiary has already died, its received fraction enters that
person's recorded estate before reaching descendants. `origin='inheritance'`
distinguishes this receipt from opening custody, including when the second
estate and its inherited property arrive on the same tick. All sibling lots
are inserted before processing deceased recipients, preserving exact fractional
conservation through converging inheritance paths. Historical queries resolve
only descendant estates opened by the selected tick.

Unfinished projects preserve the original contributor's refund rights. A
representative can finish or cancel a retained project through existing actions.
Cancellation returns actual remaining funds to their recorded contribution
accounts; only a deceased contributor's own refund enters that estate's
waterfall. A different funder's refund cannot pay the deceased owner's loan.
An unfinished project without a personal residual beneficiary follows the
existing automatic cancellation policy. Its title disposition references the
actual cancellation event. Completed no-heir assets with creditors remain in
custody pending the administration policy below.

The two new immutable tables are `estate_project_custody` and
`estate_project_releases`. Custody records the estate, exact interest lot, opening
tick, opening/inheritance origin and policy. A release records either an in-kind
distribution or an actual cancellation, with transaction, receipt, claim,
claim-release, reserve and resolution frontiers. `project_stewardships` records
estate capacity and estate ID. The schema validator, hash-v7 inventory, export
and replay comparison include this evidence; cancellation event IDs use the
existing logical event-reference mapping. Frozen earlier contracts are unchanged.

Receipts and pending asset releases drain within the same nested savepoint
batch, including refunds created by an asset's cancellation. A failure after
new title lots have been written restores the triggering payment, bank recovery,
estate records and ownership together. Reconciliation rejects unsupported
frontiers and distributions that skip creditors, even if the cash ledger alone
balances. The new evidence rejects updates, deletions and orphan releases.

Selected-tick construction projections label the nominee as an estate and
expose recorded estate capacity. Every residual beneficiary and the relevant
guardian participates in the existing core/pinned visibility check. A private
child or guardian therefore withholds the associated home across project
details, places, presence, map routes and a public person's residence. Reads
leave the authoritative hash unchanged.

Validation completed during this increment:

- The first completed-home regression failed as expected before custody was
  implemented. An implementation error assumed the project had a currency
  column; using its escrow account corrected that error, and the case passed.
- The initial property/project/securities regression passed **46 tests in
  226.83 s**, log `tmp/estate-property-custody-and-securities.log`, base
  `C:/Users/matri/.codex/tmp/ae-69516439` (74.13 GiB free at launch).
- Inheritance-chain, minor/guardian and city-privacy checks passed **22 tests
  in 87.88 s** with the existing property replay case deselected, log
  `tmp/estate-property-cascades-and-privacy.log`, base
  `C:/Users/matri/.codex/tmp/ae-750f396c` (78.83 GiB free at launch).
- The property module then passed **12 tests in 92.94 s**, including rollback,
  corrupted release evidence and actual payment/restart/export/replay, log
  `tmp/estate-property-custody-replay-and-rollback.log`, base
  `C:/Users/matri/.codex/tmp/ae-0da9b512` (78.72 GiB free at launch).
- A later converging-branches case reproduced the management-selection defect
  in 1.42 s. After summing beneficial weights, that case passed. A separate
  currency fixture initially queried the wrong claim-kind string; correcting
  it to the recorded `bank_principal` kind produced **2 passes in 1.69 s**,
  log `tmp/estate-property-combined-beneficiary-and-currency-corrected.log`,
  base `C:/Users/matri/.codex/tmp/ae-c85078df` (78.41 GiB free at launch).

After those final changes, the integrated regression passed **314 tests in
780.00 s**. It covered all fourteen Semantics-20 modules, Semantics 19 and 8,
recorded-replay golden cases, research export, exchange, documentation and five
existing provenance cases. Log: `tmp/estate-property-integrated-regression.log`;
fresh base: `C:/Users/matri/.codex/tmp/ae-8d99d2f3`. Free space was 77.04 GiB at
launch and 83.39 GiB after completion; this batch's artifacts occupied 0.794 GiB.
The existing Starlette/httpx deprecation warning remains. The run finished with
exit code zero. A file-time audit found no changed worktree source or documents
modified during the run. Staging was empty, and frozen migration/hash-contract
files had no diff. Full CI and publication remain separate from this local
regression and incomplete W5 development.

The replay fixture declares a small home built through real genesis permitting,
funding and work, a reserves-funded loan and a pre-existing payment contract.
The recorded gateway performs the contract on day two, after the owner's death;
the real payment releases the title. Source reopening preserves the committed
hash, both new tables export nonempty, fresh replay is exact, and the stored
source bytes remain unchanged. These three actual world ticks establish the
accounting and replay path. Prescribed decisions and declared adult eligibility
in focused succession cases do not establish autonomous estate decisions,
empirical prices or the required multi-decade cohort campaign.

## Implemented public administration for retained assets

`EstateAdministration` implements the declared `regional_public_trustee_v1`
research rule. If a completed estate still retains securities or project rights
and no living adult beneficiary or current guardian can act, an existing living
adult with the `gov_official` role in the deceased's region can be appointed.
The incumbent remains while eligible; a new appointment selects the lowest
eligible person ID. This is a synthetic institutional rule, not a jurisdiction's
probate law. It creates no people, endowment, beneficial interest or additional
administration fee. The actor continues to use existing decision budgets and
the original estate's currency-specific cash waterfall.

If there is no eligible official or no declared region, the engine records a
vacancy rather than manufacturing authority. A later eligible existing official
can fill it. A public appointment ends when private representation returns, the
official dies, changes region or loses the role, or no retained asset remains.
The first acceptance case reproduced an unrepresented indebted estate despite
an eligible regional official. The implemented appointment supplies authority
while title and securities remain with the nominee. Private minors keep their
residual rights and housing use; the official does not become their guardian
or acquire the home.

`estate_administrations` and `estate_administration_ends` are immutable evidence
tables. They record occupied/vacant intervals, region, role/age evidence,
policy, ending reason and matching events. Securities order authorization links
the appointment and its ending-record frontier, separate from beneficiary and
guardian paths. The frontier preserves a valid quote or fill made earlier on
the same day that an appointment ends. A false frontier that includes the
appointment's ending is rejected. Property stewardship records administrator
capacity and the exact appointment ID. Hashing, migration validation, export
and replay include the two tables and logical event references.

Order validation checks current authority at execution. A role-loss regression
also reproduced stale company/property authority before history refresh. The
controls now reassess actual eligibility and current rights at use, so an old
stewardship row cannot authorize pricing or construction after the mandate is
lost. Authority refresh records the subsequent disposition. Disposed estate
positions revoke remaining quotes at the same settlement boundary; they cannot
continue to advertise shares that have already been released in kind.

The private securities context includes appointment identity, whether the issuer
is listed, pending sale quantity, remaining quantity available to offer and the
most recent actual offer tick for that estate's position.
The default citizen/founder/government decision paths use one unreserved listed
position for a public-trustee market offer, after any required civic appointment.
Unoffered positions go first, followed by the least recently offered; ties use
estate and issuer IDs. This ordering uses recorded quote history across both
positions and estates, so an unmatched first position cannot monopolize retries.
They do not force private beneficiaries to sell, duplicate outstanding offers,
or invent an exchange for unlisted shares. A market offer without a priced
counterparty has no proceeds. Unfilled day orders can expire and be offered
again through the existing exchange rules. Real fills settle creditors and
then release the remaining assets; the public official receives no inheritance.
Normal institutional work can continue when no estate offer is available.

The public appointment does not widen observer access. The selected-day
projection still considers every residual beneficiary and the administrator;
a private child withholds the home through project detail, places, presence,
map routes and a public co-beneficiary's residence. Read-only projections leave
the authoritative hash unchanged.

Focused evidence before the final broader regression:

- The initial missing-administrator case failed in **1.30 s**, then passed in
  **1.11 s** after implementation. Logs:
  `tmp/estate-public-administration-baseline.log` and
  `tmp/estate-public-administration-first.log`.
- **11 tests passed in 11.20 s** for actual funded settlement, vacancy, role/
  region/death revocation, guardian return, rejection and whole-death rollback.
  Log: `tmp/estate-public-administration-scope-and-settlement.log`; base
  `C:/Users/matri/.codex/tmp/ae-95a5f03e`; initial free space 82.85 GiB.
- The combined administration/property/securities run produced **56 passes and
  one fixture failure in 206.42 s**. The official offered shares, but the declared
  buyer entered the periphery path and did not submit the intended quote.
  Pinning that counterparty to the recorded gateway corrected the fixture.
  The standalone full-world case then passed in **74.50 s**, log
  `tmp/estate-public-administration-recorded-counterparty.log`, base
  `C:/Users/matri/.codex/tmp/ae-5a14f7ac`; initial free space 82.62 GiB.
- The stale public-role control case failed in **1.36 s**, then passed in
  **1.08 s** after the immediate authority check. The final authority and
  private-child projection pair passed **2 tests in 7.62 s**, log
  `tmp/estate-public-administration-privacy-and-authority.log`, base
  `C:/Users/matri/.codex/tmp/ae-bb79ff8b`; initial free space 82.47 GiB.

The integrated regression then passed **331 tests in 865.76 s**, with the
existing Starlette/httpx deprecation warning. The target list was the preceding
314-case property regression plus
`tests/test_semantics20_estate_administration.py`. It used
`-v --tb=short --maxfail=3 --basetemp C:/Users/matri/.codex/tmp/ae-26904fdd`.
Log: `tmp/estate-public-administration-integrated-regression.log`; metadata:
`tmp/estate-public-administration-integrated-regression-meta.json`. Initial free
space was 82.43 GiB and afterward 81.61 GiB; its artifacts occupied 0.868 GiB.
All 1,070 source-snapshot files retained their content hashes and modification
times throughout the run. Staging was empty and frozen migrations/hash-v1–v6
had no diff.

A later policy review found starvation of other retained positions: after an
unmatched day order expired, stable ID ordering chose it again even with a
priced buyer for a second position. The first fixture attempt used a nonexistent
`citizen` role; ordinary citizens in this fixture have a null role. After that
fixture correction, both one-estate/two-position and two-estate cases reproduced
the actual failure in **1.78 s**. Log:
`tmp/estate-public-administration-rotation-confirmed-baseline.log`, base
`C:/Users/matri/.codex/tmp/ae-d4c78383`, initial free space 81.59 GiB.
The quote-history selection above then passed both actual funded-sale cases in
**1.65 s**, log `tmp/estate-public-administration-rotation-corrected.log`, base
`C:/Users/matri/.codex/tmp/ae-96783bac`, initial free space 81.59 GiB. It adds no
cursor, clock-dependent rotation or authoritative table. The final affected
estate, export and replay regression passed **76 tests in 328.59 s** after this
refinement; the 331-case run preceded it. The final command was:

```powershell
$estateFinalTargets = @(
  'tests/test_semantics20_estate_administration.py',
  'tests/test_semantics20_estate_property.py',
  'tests/test_semantics20_estate_securities.py',
  'tests/test_recorded_replay_golden.py',
  'tests/test_research_export.py',
  'tests/test_prd_completion.py::test_replay_compares_llm_provenance_by_logical_call_identity',
  'tests/test_prd_completion.py::test_replay_rejects_same_actor_turn_wrong_llm_purpose',
  'tests/test_prd_completion.py::test_replay_canonicalizes_communication_model_provenance',
  'tests/test_prd_completion.py::test_replay_validates_legal_model_reference_owners',
  'tests/test_prd_completion.py::test_replay_reports_legacy_missing_llm_table_without_crashing'
)
.\.venv\Scripts\python.exe -u -m pytest -v --tb=short @estateFinalTargets --maxfail=3 --basetemp C:/Users/matri/.codex/tmp/ae-845f4743
```

Log: `tmp/estate-public-administration-final-policy-replay.log`; metadata:
`tmp/estate-public-administration-final-policy-replay-meta.json`. Free space
was 81.58 GiB at launch and 81.30 GiB afterward; artifacts occupied 0.252 GiB.
All 1,070 source-snapshot files retained their hashes and modification times
through the final run. Staging remained empty. Eleven affected Python files
passed AST and trailing-whitespace checks; normal `git diff --check` passed.
The only pytest warning was the existing Starlette/httpx deprecation warning.

The full-world case builds a small real home and declares a listed issuer and
reserves-funded loan at genesis. The owner dies in the actual world cycle. The
official's default policy supplies estate offers; only the buyer is prescribed
as a funded liquidity counterparty. Three world ticks include source restarts,
nonempty appointment/ending and property-custody exports, exact recorded replay
and unchanged source-file bytes. This establishes the default trustee decision
and settlement path, not an empirical price result or multi-decade evidence.

## Implemented disinterested estate adjudication

Semantics 20 now declares `disinterested_estate_adjudication_v1` in
`LegalDecisionAuthority`. A decision requires an existing living adult in an
authorized decision role. Personal parties, named counsel, current party
controllers, positive personal shareholders and current estate representatives
cannot adjudicate their own interests. A public estate appointment or estate
business stewardship creates a persistent conflict for that party, including
after the appointment ends. A partial death settlement cannot admit a decision.
Rejection leaves the matter undecided and moves no money.

An eligible decision records its authority before enforcement. The new immutable
`legal_decision_authorities` table binds the decision maker, age, role, policy,
tick and the existing estate, administration and business-stewardship frontiers.
`firm_stewardships.recorded_event_id` distinguishes when an interval was recorded
from an earlier economic start date, including bootstrap founder intervals.
Reconciliation reconstructs those frontiers from event order. It rejects omitted
earlier appointments without treating a later same-day appointment as an earlier
conflict. Authority recording, enforcement, award settlement and resulting
estate transfers share the rollback boundary. All 33 succession tables and both
new event references participate in export, hash-v7 and exact replay.

This is a declared simulation rule. Permanent public-administration and estate
business conflicts have reconstructible history; the private beneficiary,
guardian, controller and shareholder checks use authority at admission. This
increment does not supply complete historical reconstruction of every changing
private financial interest, a general representation lifecycle, appeals or a
jurisdiction's adjudication rules.

Existing officials receive a bounded private queue of due, unanswered matters
with admitted evidence and a requested remedy. A respondent filing withholds
the case from the default unanswered-claim policy. The queue skips conflicted
cases and can expose a later eligible one. It follows the official through
ordinary citizen, judge and founder contexts, including when role-specific
purposes are disabled. Default decisions prioritize the eligible matter while
preserving a required civic appointment. A vacancy or contested matter remains
unresolved; the engine does not create an official or fabricate a decision.

The full-world acceptance case also exposed a real later-receipt failure:
`perform_obligation` triggered estate settlement events with a nightly default
phase, causing its proposal-to-event causal edge to run backward. Semantics-20
successful actions now assign their own phase to only the fresh, uncommitted
events carrying that nightly default, before causal edges bind. Earlier events,
ordinary nightly processing, prior semantics and the causal ordering rule remain
intact. The test uses the real contract-payment action and real payer funds.

Focused evidence, before the final combined regression:

- The public trustee was accepted on either side of its estate's dispute in
  two failing baseline cases (**1.70 s**), then both rejected correctly
  (**1.61 s**). Logs: `tmp/estate-legal-authority-baseline.log` and
  `tmp/estate-legal-authority-first.log`; bases `ae-11882986` and `ae-4bfddfee`.
- The first expanded run had **15 passes and one expectation failure / 18.69 s**:
  the executor already rejected the minor with a different message. The test
  now separately checks direct legal admission. The legal integration run then
  passed **42 tests / 94.06 s**, log
  `tmp/estate-legal-authority-legal-integration.log`, base `ae-78dbfde6`.
  These results preceded the later recording/frontier and policy refinements.
- Two tampered-frontier cases reproduced missing historical checks
  (**1.88 s**). After recording business intervals and reconstructing exact
  frontiers, **19 tests passed / 20.99 s**, log
  `tmp/estate-legal-authority-frontiers-corrected.log`, base `ae-9be65332`.
- The first world case failed **1 test / 7.53 s** because the contract payment
  hit the causal-phase failure above; recusal itself worked. Log:
  `tmp/estate-legal-authority-world-replay.log`, base `ae-dd489186`.
  After correction, the three-day source/restart/export/exact-replay case
  passed **1 test / 67.39 s**, log
  `tmp/estate-legal-authority-world-replay-phase-corrected.log`, base `ae-f2750958`.
  Later assertions additionally preserve earlier nightly phases and verify
  the payment's forward causal edge; they belong to the combined run below.
- Actual context construction reproduced **4 failures and 1 pass / 5.86 s**:
  judges, officials without role-specific purposes and a trustee operating a
  company missed the queue. After the version-gated attachment, all five cases
  passed **8.58 s**, log `tmp/estate-legal-authority-context-corrected.log`,
  base `ae-f7c3169e`; initial free space 80.74 GiB.

All these bases are under `C:/Users/matri/.codex/tmp/`; each launch checked at
least 40 GiB free. The world fixture declares one mortality draw, official
availability and the funded counterparty's payment. The replacement official's
actual decision uses the default policy and recorded context. Three ticks,
nonempty authority exports, restart continuity and source-preserving replay are
acceptance evidence, not a cohort study or a multi-decade price-discovery result.
The combined regression passed **378 tests / 936.33 s** with the existing
Starlette/httpx deprecation warning. It includes the final actual-context and
causal-phase assertions. The exact targets and options were:

```powershell
$estateAuthorityTargets = @(
  'tests/test_semantics20_cash_offsets.py',
  'tests/test_semantics20_civic_succession.py',
  'tests/test_semantics20_estate_administration.py',
  'tests/test_semantics20_estate_cases.py',
  'tests/test_semantics20_estate_disputes.py',
  'tests/test_semantics20_estate_property.py',
  'tests/test_semantics20_estate_securities.py',
  'tests/test_semantics20_legal_authority.py',
  'tests/test_semantics20_legal_awards.py',
  'tests/test_semantics20_legal_projection.py',
  'tests/test_semantics20_personal_authority.py',
  'tests/test_semantics20_personal_commitments.py',
  'tests/test_semantics20_project_rights.py',
  'tests/test_semantics20_service_commitments.py',
  'tests/test_semantics20_succession.py',
  'tests/test_semantics20_wage_awards.py',
  'tests/test_semantics19_estate_cash.py',
  'tests/test_semantics8_foundations.py',
  'tests/test_semantics8_causal_membership.py',
  'tests/test_v2_legal.py',
  'tests/test_recorded_replay_golden.py',
  'tests/test_research_export.py',
  'tests/test_exchange.py',
  'tests/test_documentation.py',
  'tests/test_prd_completion.py::test_replay_compares_llm_provenance_by_logical_call_identity',
  'tests/test_prd_completion.py::test_replay_rejects_same_actor_turn_wrong_llm_purpose',
  'tests/test_prd_completion.py::test_replay_canonicalizes_communication_model_provenance',
  'tests/test_prd_completion.py::test_replay_validates_legal_model_reference_owners',
  'tests/test_prd_completion.py::test_replay_reports_legacy_missing_llm_table_without_crashing'
)
.\.venv\Scripts\python.exe -u -m pytest -v --tb=short @estateAuthorityTargets --maxfail=3 --basetemp C:/Users/matri/.codex/tmp/ae-9f0116b2
```

Log: `tmp/estate-legal-authority-integrated-regression.log`; exact metadata:
`tmp/estate-legal-authority-integrated-regression-meta.json`. Free space was
80.72 GiB before launch and 79.68 GiB afterward; artifacts occupied 1.016 GiB.
All 1,072 source-snapshot files retained their hashes and modification times,
with no added or removed source files during the run. Staging stayed empty.
A command-preparation check initially caught an incorrect test filename before
launch; the verified module in this completed command is `tests/test_v2_legal.py`.

A subsequent review found that an invalid requested remedy could occupy the
first work-queue slot indefinitely. Actual filed matters with unsupported
relief, an amount above the rule limit and a malformed amount reproduced
**3 failures / 10.64 s**, log
`tmp/estate-legal-authority-remedy-queue-baseline.log`, base `ae-54a56940`.
The queue now applies the engine's read-only remedy validation, reports up to
five blocked matters with reasons, and continues to a valid later case. It does
not dismiss or rewrite the invalid claim. All three actual decision cases then
passed **18.67 s**, log `tmp/estate-legal-authority-remedy-queue-corrected.log`,
base `ae-86be4c63`; initial free space 79.67 GiB. The 378-case regression preceded
this last queue refinement. The final affected-policy and replay regression
passed **86 tests / 320.00 s** afterward, with only the existing Starlette/httpx
deprecation warning. Its exact command was:

```powershell
$estateAuthorityFinalTargets = @(
  'tests/test_semantics20_legal_authority.py',
  'tests/test_semantics20_legal_awards.py',
  'tests/test_semantics20_estate_disputes.py',
  'tests/test_semantics20_estate_administration.py',
  'tests/test_v2_legal.py',
  'tests/test_recorded_replay_golden.py',
  'tests/test_research_export.py',
  'tests/test_prd_completion.py::test_replay_compares_llm_provenance_by_logical_call_identity',
  'tests/test_prd_completion.py::test_replay_rejects_same_actor_turn_wrong_llm_purpose',
  'tests/test_prd_completion.py::test_replay_canonicalizes_communication_model_provenance',
  'tests/test_prd_completion.py::test_replay_validates_legal_model_reference_owners',
  'tests/test_prd_completion.py::test_replay_reports_legacy_missing_llm_table_without_crashing'
)
.\.venv\Scripts\python.exe -u -m pytest -v --tb=short @estateAuthorityFinalTargets --maxfail=3 --basetemp C:/Users/matri/.codex/tmp/ae-e44e90b0
```

Log: `tmp/estate-legal-authority-final-policy-replay.log`; metadata:
`tmp/estate-legal-authority-final-policy-replay-meta.json`. Free space was
79.65 GiB at launch and 79.34 GiB afterward; artifacts occupied 0.289 GiB.
All 1,072 source files retained their content hashes and modification times
through this final run. Twelve affected Python files passed AST and whitespace
checks; normal `git diff --check` passed. Staging was empty and frozen migrations
through v024 and hash contracts through v6 had no diff. No cleanup, paid provider
calls, unrelated process stops, staging, commits, publication or merges were
performed in this increment. Semantics 20 remains unpublished and extensible.

The final documentation check passed **22 tests / 0.35 s** using
`tests/test_documentation.py` and fresh base
`C:/Users/matri/.codex/tmp/ae-b7b2158f`, with 79.34 GiB free at launch.
Log: `tmp/estate-legal-authority-documentation.log`.

### Recorded representation and consenting counsel

The unpublished Semantics-20 policy `recorded_party_mandates_v1` now checks
standing for the named party at claim filing, evidence submission, settlement
offer and acceptance. `engine/legal_representation.py` reuses current estate
custody, guardian and public-appointment proofs while retaining the deceased's
party identity. It does not extend generic `LegalInstitution.controls` or
authorize new personal borrowing and unrelated contracts.

The four immutable journals are `legal_action_authorities`,
`legal_counsel_requests`, `legal_counsel_responses` and `legal_counsel_ends`.
An authority event precedes its recorded legal effect. Historical reconciliation
checks party identity, consent, scopes, actor age, captured authority frontiers
and effect binding. The adjudication proof also captures the counsel-response
frontier: accepting either side permanently conflicts that lawyer from later
deciding the same matter, including after withdrawal or a role change.

The command contract is:

- `request_legal_counsel{matter_id,side,counsel_agent_id,scopes}` requires the
  client's direct authority, another living adult lawyer and an open matter.
  `side` is `claimant` or `respondent`; supported scopes are `submit_filing`,
  `propose_settlement` and `accept_settlement`. The default scopes omit
  settlement acceptance. A pending request expires after seven ticks. There
  is one current request per side; accepted mandates persist until ended.
- `respond_legal_counsel{request_id,decision}` records the requested lawyer's
  `accept` or `decline`. Naming a lawyer in `file_claim` creates a pending
  request and returns `counsel_request_id`; it never supplies that consent.
- `end_legal_counsel{request_id}` lets a directly authorized client revoke or
  the accepted lawyer withdraw. Client authority loss, death, lost lawyer
  qualification, pending expiry and matter closure append automatic endings.
  Replacement creates a new request and preserves every earlier response.

A filing must name one of the original parties. Control of an unrelated
identity and self-appointment by a lawyer are rejected. Settlement acceptance
requires authority for the opposite party, its explicit scope when delegated,
and a still-authorized offer proposer. Actual payment remains a ledger effect;
the current mandate creates no legal fee or new funds.

Public administration now continues for an open estate-party matter after the
last security or property is released, and can appoint a representative to an
estate with only that legal work. Open matters were the first implemented
boundary. The retained-receivable extension below also covers unfiled payment,
indemnity and earned-wage rights. Existing automatic award collection from
actual later estate receipts has the payment/replay coverage above.
Existing private representation returning and public vacancy/authority-loss
rules remain effective.

Current decision contexts expose at most five accepted or directly represented
estate matters and twelve relevant factual events per matter, bounded at the
requested tick. Prompts show pending consent, the represented party and allowed
actions. Default action policies can accept a pending request, file supported
evidence under the client's identity and offer a validated requested remedy.
Each side may address evidence already filed by the other side. Required civic
attendance and eligible disinterested adjudication retain their priority.
Coverage includes the direct policy registry, periphery dispatch and an actual
heir/founder context. These current decision views are not the unfinished
selected-tick historical estate interface.

Initial evidence: three standing failures reproduced in 2.23 s, then passed in
2.18 s; nineteen consent and funded-settlement checks passed in 14.69 s. The
missing prompt contract then reproduced three failures in 2.18 s, followed by
34 context/representation passes in 21.30 s. A four-day default-counsel,
save/restart, actual-payment, nonempty-export and exact-recorded-replay case
passed in 97.73 s, with the source database hash unchanged. These results
precede the final per-party evidence and bounded-query refinements; final
regression evidence is recorded below. Logs are
`tmp/estate-legal-representation-context-baseline.log`,
`tmp/estate-legal-representation-context-corrected.log` and
`tmp/estate-legal-representation-world-replay-first.log`. Their fresh bases were
`C:/Users/matri/.codex/tmp/ae-cc1cec80`, `ae-852db08f` and `ae-d462c63d`, with
78.90, 78.89 and 78.77 GiB free at launch respectively.

The first representation checkpoint rejected all dual-party authority. The
extension below admits explicit procedural work while preserving the settlement
and adjudication restrictions. These checks do not establish a complete history
of every changing professional qualification or private financial interest;
the authority proof retains the specific recorded custody and appointment
boundaries described above.

### Final representation regression

The combined regression finished with **417 passed and 1 failed / 1182.19 s**.
It included all seventeen `tests/test_semantics20_*.py` modules,
`tests/test_semantics19_estate_cash.py`, `tests/test_semantics8_foundations.py`,
`tests/test_semantics8_causal_membership.py`, `tests/test_v2_legal.py`,
`tests/test_recorded_replay_golden.py`, `tests/test_research_export.py`,
`tests/test_exchange.py`, `tests/test_documentation.py` and the five
`tests/test_prd_completion.py` provenance nodes listed in the preceding
combined-regression command. Python options were `-X utf8 -u -m pytest -v
--tb=short --maxfail=3`, with a fresh base
`C:/Users/matri/.codex/tmp/ae-513c958d` after the 40-GiB guard.

The one failure was the `claimant` parameter of
`test_wage_filing_rejects_other_parties_currency_and_future_work_without_a_partial_matter`.
Its proposed claimant owned the respondent employer, so the new dual-party
authority rule correctly rejected the action before wage-ownership validation.
The test now uses the fixture's other living adult for the wrong-worker case
and separately verifies the original dual-party rejection. Both retain the
assertion that the failed filing leaves the authoritative hash unchanged.
No engine, policy, schema or replay code changed after the combined run.

The complete corrected wage module then passed **18 tests / 62.44 s** with
the same Python options, target `tests/test_semantics20_wage_awards.py` and
fresh base `C:/Users/matri/.codex/tmp/ae-93a35190`. This is a focused follow-up;
the combined run is retained as 417 passes and one fixture failure, not relabeled
as a clean rerun of all cases. All 37 representation cases, including the
four-day default-policy/restart/export/exact-replay case, passed in the combined
run on the final engine source.

Receipts are `tmp/estate-legal-representation-integrated-regression.log` and
`tmp/estate-legal-representation-final-wages.log`, each with `-meta.json` and
`-source.json` companions containing exact targets/options and file hashes and
modification times. All 1,074 source files remained unchanged throughout each
run; staging remained empty. Combined free space was 78.75 GiB before and
77.05 GiB afterward, with 1.192 GiB in its fresh test directory. The wage run
started at 77.05 GiB and finished at 76.78 GiB, with 0.050 GiB of test artifacts.
Only the existing Starlette/httpx deprecation warning appeared.

The 67 changed/new Python files passed AST and whitespace checks. Normal
`git diff --check` passed, and frozen migrations through v024 and hash contracts
through v6 had no changes. The complete Python CI shards and release gate remain
publication requirements. No paid providers, cleanup, staging, commits,
publication or merges were performed in this continuation.

Final documentation validation passed **22 tests / 0.36 s**, with 76.78 GiB
free and a fresh `C:/Users/matri/.codex/tmp/ae-146b490f` base. Its log and
unchanged-source receipt use the prefix
`tmp/estate-legal-representation-documentation`.

### Retained financial rights and explicit procedural sides

The derived `recorded_estate_receivables_v1` policy in
`engine/estate_legal_work.py` retains pending or breached payment/indemnity
obligations and unpaid earned wages under the deceased's original identity.
These rights now keep public administration available without requiring an
existing case or a remaining security/property. Actual early payment can end
that appointment without inventing a dispute. Replacement award obligations
stay with the existing automatic collection path.

Agent contexts expose at most five rights and one eligible filing action.
Unfiled contractual claims require an actual recorded breach at or before the
decision tick; wage claims require recorded missed payment and an eligible
earned interval. Stable source keys identify each obligation or wage claim.
An already-presented obligation or wage interval is not automatically filed
again, including after a case closes. An oversized or otherwise blocked first
right does not prevent consideration of later eligible rights. This is a
bounded current decision view, not a historical portfolio reconstruction.

Default policies can file the original nominee's claim, supply actual evidence
and offer the supported remedy. Contract relief states the original entitlement;
the existing award engine credits actual prior payments. Earned-wage relief uses
the recorded interval and currency. The opportunity creates neither a price nor
cash, and it does not choose consenting counsel on the client's behalf.

One adult may represent both original parties through separate direct capacities,
such as personal ownership and inheritance, or public appointments for two
estates. Explicit claimant/respondent sides now permit procedural filing and
counsel administration. The authority proof captures both direct capacities;
reconciliation verifies the opposing grant at the same recorded boundaries.
Dual control still rejects settlement offers and acceptance. Such a client can
request only `submit_filing` counsel scope, with actual lawyer consent. Existing
financial mandates end if the client gains the opposing party's authority, or
if the lawyer becomes conflicted. A representative cannot decide their own
case; an existing independent qualified official must do so.

This extension adds no schema tables or columns. The unpublished Semantics-20,
schema-25/hash-v7 contract retains 37 succession tables and inventory hash
`10bc62e3be8de3651e8b9daa15b58e662fc109ddfb3c329a2b67bae9956c4131`.

Initial tests reproduced five failures in 2.95 s for missing unfiled-right
contexts, absent public appointments and rejected procedural standing. Those
five passed in 2.61 s after implementation. The expanded run produced eleven
passes and one timeline-fixture failure in 6.02 s: actual estate completion and
the default trustee's filing both occur on day one, in that event order. The
fixture was corrected to assert recorded ordering rather than an extra day.

The resulting module passed **12 tests / 116.17 s**, including a five-day actual
world with a default public trustee, daily close/reopen, a funded 100-cent
settlement, appointment ending, nonempty authority export and exact recorded
replay without provider calls. The source database file hash remained unchanged.
Log and source/storage receipts:
`tmp/estate-legal-representation-retained-replay.log`, `-meta.json` and
`-source.json`; fresh base `C:/Users/matri/.codex/tmp/ae-2600ee46`.
All 1,076 source files retained their hashes and modification times; staging
remained empty. This result precedes one added visibility assertion and the
expanded dual-party test described next.

Both private-heir and public-trustee dual-party cases then passed in **1.61 s**,
including explicit briefs from each side, consenting procedural counsel,
rejected self-settlement and self-adjudication, independent judgment and actual
10-cent payment. Log: `tmp/estate-retained-legal-rights-dual-party.log`; fresh
base `C:/Users/matri/.codex/tmp/ae-6b3427a2`, with 76.15 GiB free at launch.
The complete new module has thirteen cases. The combined regression below
covers this final source together with prior estate and legacy behavior.

### Final retained-right regression

The combined regression passed **432 tests / 1275.46 s**, including all eighteen
`tests/test_semantics20_*.py` modules and every legacy, export, exchange,
documentation and provenance target listed in the earlier final-representation
regression. All thirteen retained-right cases passed on the final source,
including the expanded private/public procedural cases and the five-day default
public-trustee payment/restart/export/exact-replay case.

The invocation was:

```powershell
.\.venv\Scripts\python.exe -X utf8 -u tmp/run_representation_regression.py estate-legal-representation-retained-integrated
```

This local evidence helper expands to `-X utf8 -u -m pytest -v --tb=short
--maxfail=3` with the exact 31 targets recorded in
`tmp/estate-legal-representation-retained-integrated-meta.json`. It checked the
40-GiB minimum and created fresh base
`C:/Users/matri/.codex/tmp/ae-5afc5887`. The matching `.log` and `-source.json`
retain the full test output and source hashes/modification times. The helper
and receipts are local ignored artifacts; the test modules remain the maintained
verification targets. Always create a new short base for a later run.

All 1,076 source files kept their hashes and modification times throughout the
run. Staging remained empty. Free space was **76.14 GiB before and 75.28 GiB
afterward**; the test directory contains **1.251 GiB** of artifacts. Only the
existing Starlette/httpx deprecation warning appeared. All 69 changed/new Python
files passed AST and whitespace checks, and normal `git diff --check` passed.
Frozen migrations through v024 and hash contracts through v6 had no changes.
The final documentation-only check uses `tests/test_documentation.py` and the
receipt prefix `tmp/estate-legal-representation-retained-documentation`.

This is focused local validation, not the complete Python CI or release gate.
No cleanup, paid providers, unrelated process stops, staging, commits,
publication or merges occurred in this continuation. Full W5 and W6–W9 remain
open; the next implementation is financial asset disposition below.

### Funded disposition of retained property

`EstatePropertySales` now implements `funded_whole_interest_bids_v1` under
Semantics 20. Its three immutable journals are `estate_property_bids`,
`estate_property_bid_ends` and `estate_property_sales`. They are included in the
unpublished v025/hash-v7 inventory, research export and recorded replay.

1. `place_estate_property_bid` identifies one retained custody lot and an actual
   buyer-owned cash wallet. The offer covers that lot's entire exact fraction,
   which may be less than the whole property. It records a positive integer-cent
   total price up to 1,000,000,000,000, the property's escrow currency, an expiry
   within the next 30 ticks and a request key. Expiry is exclusive. The buyer
   must be a living adult and cannot currently represent the selling estate.
   The same key and terms return the existing bid; altered terms are rejected.
2. A bid requires funds when placed but does not reserve them. Acceptance
   rechecks available cash, wallet ownership, currency, adult/living status,
   active custody, expiry and current representative authority. A buyer can
   withdraw an open bid. Expiry, buyer death, custody disposal and project
   cancellation produce recorded endings. Rejection preserves money and title;
   the normal proposal and rejection-event journals still record the attempt.
3. `accept_estate_property_bid` transfers real cash through the ledger into the
   original nominee wallet inside `EstateCases._batch()`. It ends the parent
   interest, creates the buyer's successor with exactly the same fraction,
   records custody disposition `sold`, captures the representative's capacity
   and ends the bid before the queued estate receipts are distributed. Creditors
   retain their priority; children receive their own residual cash. Original
   construction ownership, work, contributions and refund entitlements remain
   unchanged. Failure during payment, title or residual distribution rolls back
   the entire settlement and permits a clean retry.
4. Property reconciliation now distinguishes a funded sale from inheritance.
   It verifies exact fractions, prior/current title, the sale and bid events,
   historical authority, actual ledger legs, available pre-sale funds and the
   linked estate receipt. Historical ownership and stewardship retain their
   existing interval semantics. Property sales do not create exchange trades
   or supply a general market valuation for unsold property.
5. Decision contexts provide bounded actual offers, the actor's own funded
   wallets and exact authorized acceptance/withdrawal actions. Default role
   policies select the highest currently funded bid for the oldest eligible
   custody lot, with bid ID breaking ties, after required civic work. They
   search beyond blocked offers and carry the selected bid's exact terms.
   Citizen/participant catalogs and prompts expose bidding and withdrawal as
   well as authorized acceptance. Private/public/guardian authority is enforced
   again by the engine at execution. Property-bid form normalization accepts
   exact integers or integer text, rejects fractional numeric input and enforces
   the displayed price/expiry bounds. Server-owned custody, wallet, currency
   and request-key fields cannot be redirected by the client. Earlier action
   types retain their historical normalization.

The three-day world fixture forces an owner death and declares one funded
buyer; the existing trustee's default policy accepts the bid. Each day closes
and reopens the database, all three new journals export with actual rows, and
recorded replay reproduces the result without calling the scripted adapter or
changing the source file. A separate two-death household case sells one retained
half-interest and preserves the child's other half. A buyer also purchases an
unfinished project and completes it through actual work actions; original
contributions and the deceased funder's refund entitlement remain intact.
The cross-bank case verifies both deposit legs and both reserve legs of the
sale payment, followed by actual creditor settlement. These are acceptance
fixtures; they do not establish emergent property-price discovery or a calibrated
buyer valuation policy. The current decision context is not a historical wealth
report. Existing selected-tick ownership/privacy regressions remain required;
this slice does not claim a review of every legacy raw-event surface.
Context output is bounded, but scans of retained lots and bids have not been
benchmarked at scale. Include their query counts in W9's population and horizon
measurements before a large demographic campaign.

The initial implementation had three missing-action failures. Subsequent test
corrections covered expected rejection journals, the actual ContextBuilder and
scripted-policy signatures, eligible household participants, prior family
contact and a supported birth tick. Earlier receipts are retained below;
failure counts are not presented as successful combined runs.

| Receipt suffix | Result | Fresh test base |
| --- | --- | --- |
| `baseline` | 3 failed / 2.35 s | `ae-2c9d29b9` |
| `first` | 2 passed, 1 failed / 8.53 s | `ae-ebed6972` |
| `mechanics` | 33 passed, 1 failed / 71.63 s | `ae-ef9fab8e` |
| `world` | 14 passed, 2 failed / 144.38 s | `ae-23b2d833` |
| `corrected-fixtures` | 1 passed, 1 failed / 2.29 s | `ae-81b17f1d` |
| `fraction` | 1 failed / 1.43 s | `ae-3e6f8159` |
| `fraction-corrected` | 1 passed / 1.64 s | `ae-e8dfb26b` |
| `complete` | 27 passed / 249.84 s | `ae-64a1ac53` |
| `integrated` | 294 passed / 863.04 s | `ae-94cbb0dc` |
| `controls-baseline` | 1 passed, 1 failed / 2.08 s | `ae-52b9d9c3` |
| `final-controls` | 68 passed / 226.36 s | `ae-b6f6d37e` |

Receipt prefixes are `tmp/estate-legal-representation-property-sale-<suffix>`
with `.log`, `-meta.json` and `-source.json`; bases are under
`C:/Users/matri/.codex/tmp/`. The 27-case run includes guardian,
invalid-bid and citizen-catalog checks before the last input correction.
All 1,078 source files retained their
hashes and modification times; staging stayed empty. Free space was
83,207,684,096 bytes before launch and 81,659,195,392 afterward; test artifacts
occupied 111,746,014 bytes. The prior 432-case regression predates property-sale
implementation.

The 294-case affected regression includes the cross-bank sale; estate cases,
property, securities, administration, title, legal representation and retained
rights; legacy Semantics-19 cash; schema/causal foundations; v2 legal behavior;
golden replay; research export; exchange; participant and external-agent control;
documentation; and five existing replay-provenance cases. Its `-meta.json`
records every exact target. All 1,078 source hashes and modification times stayed
fixed, with empty staging. Initial/final free space was 81,653,317,632 /
80,718,196,736 bytes; artifacts occupied 898,936,928 bytes.

The subsequent control test reproduced the old form normalizer converting a
fractional bid to an integer instead of rejecting it (`DID NOT RAISE
ParticipantError`). The unfinished-project case passed in that same two-case
run. The correction is restricted to Semantics-20 property-bid fields. Only
`agents/participant.py` and the property-sale test module changed between the
294-case run and final verification; source receipts confirm that boundary.

The final run passed all **29 property-sale cases** and the full participant,
external-gateway and golden-replay modules: **68 tests / 226.36 s**. It exercised
the corrected real catalog, rejected fractional/oversized terms, preserved the
server-owned fields and repeated daily restart/export/exact replay. All 1,078
source files again retained their hashes and modification times; staging stayed
empty. Initial/final free space was 80,710,438,912 / 80,432,275,456 bytes;
artifacts occupied 240,888,799 bytes.

To repeat the final target set from the repository root in PowerShell:

```powershell
if ((Get-PSDrive -Name C).Free -lt 40GB) { throw 'Less than 40 GiB free' }
$estateSaleBase = Join-Path 'C:\Users\matri\.codex\tmp' ('ae-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
$estateSaleTargets = @(
    'tests/test_semantics20_property_sales.py'
    'tests/test_participant_mode.py'
    'tests/test_external_agent_gateway.py'
    'tests/test_recorded_replay_golden.py'
)
& .\.venv\Scripts\python.exe -X utf8 -u -m pytest -v --tb=short --maxfail=3 @estateSaleTargets --basetemp $estateSaleBase
```

Keep source, documentation and staging fixed throughout scientific verification.
All 74 changed/new Python files passed AST/whitespace checks; the two final
edits were checked again afterward. Normal `git diff --check` passed, with
Git's existing LF/CRLF conversion advisories. Frozen migrations through v024
and hash manifests through v6 have no changes. Only the existing
Starlette/httpx deprecation warning appeared in pytest. The documentation-only
check uses `tests/test_documentation.py` and receipt prefix
`tmp/estate-legal-representation-property-sale-documentation` with another fresh
short base and the same free-space/source checks. Full Python CI shards and
the release gate remain publication requirements. No cleanup, paid providers,
unrelated process stops, staging, commits, publication or merges occurred.

### Implemented funded disposition: unlisted securities

`EstateUnlistedSales` implements `funded_whole_unlisted_lot_bids_v1` under
Semantics 20. A living adult buyer declares the entire remaining quantity of
one retained private-company lot, an owned cash wallet, exact total integer-cent
consideration, matching currency, expiry and idempotency key. Bids do not reserve
cash. The current representative accepts only while the buyer, funds, authority,
private issuer status and uncommitted nominee quantity remain eligible. A buyer
cannot also represent the selling estate. Withdrawal and terminal bid endings
are recorded; an issuer listing leaves actual trades on the existing exchange.

The unpublished schema/hash extension adds `estate_unlisted_bids`,
`estate_unlisted_bid_ends` and `estate_unlisted_sales`. Listed-sale frontiers
preserve the quantity used for each private bid and settlement. Shared lot
accounting subtracts both listed allocations and private sales before custody,
release, order reservation and business control use the remaining quantity.

Acceptance transfers actual cash through the ledger, moves the shares, records
the sale and ending, drains nominee receipts and creditor/residual payments,
and refreshes effective business control inside one outer savepoint. Failure
after receipt distribution or during control refresh rolls everything back.
Issued supply, original founder identity and other holders remain intact. The
share movement records exact total consideration, with no rounded per-share
price; it does not create an exchange execution or a stock-price observation.
Sale journals and their share movements are immutable and checked against their
funded ledger, authority, event and custody evidence.

Agent context, prompts and citizen catalogs expose bounded actual lots and bids.
Strict bid controls preserve integer terms and server-owned lot/wallet identity.
The default representative accepts the highest currently funded bid for the
first eligible lot, after existing civic obligations and property-sale priority.
Buyers still need to choose an explicit price; this policy supplies no inferred
valuation or automatic demand for a retained illiquid asset.

Focused development evidence: the first action baseline failed as expected;
the first implementation exposed a fixture with no fully specified USD currency
record. After correcting that fixture, both private/public funded-sale cases
passed. The expanded module then passed **33 cases with one assertion-pattern
failure / 172.45 s**: the ledger correctly rejected tampering as unbalanced, while
the test expected the word "funded". Correcting that expected message and adding
wallet-conflict and world coverage produced **4 passes / 87.00 s**. No production
code changed between those last two runs.

The three-day world case declares an owner death and a funded buyer; the existing
trustee uses its default acceptance policy. Daily restarts, catalog validation,
nonempty export of all three new tables and exact recorded replay passed, with
the stored source file unchanged and no replay provider calls. Other focused
cases cover guardian ownership of residual cash, exact consideration for seven
shares, preservation of another owner, successive estates, listing transition,
stale/rejected bids, and rollback/retry at payment, custody and control boundaries.
Successive estates are not biological cohort or multi-decade evidence.

Receipts: `tmp/estate-legal-representation-unlisted-sale-mechanics` used
`C:/Users/matri/.codex/tmp/ae-5d8d7216`; the final four-case run used
`tmp/estate-legal-representation-unlisted-sale-world` and
`C:/Users/matri/.codex/tmp/ae-d087c3cd`. All 1,080 source files retained their hashes
and modification times, with empty staging. The latter run ended with
80,007,376,896 bytes free and 22,181,485 bytes of test artifacts.

The final affected regression passed **219 tests / 913.36 s**, including all
37 private-share cases, all 29 property-sale cases, listed estate securities,
administration, cash estates, business succession, legacy/schema/causal checks,
research export, golden replay, participant controls and the external gateway.
Receipts use `tmp/estate-legal-representation-unlisted-sale-integrated` (`.log`,
`-meta.json`, `-source.json`); the fresh test base was
`C:/Users/matri/.codex/tmp/ae-8d04c2a5`. All 1,080 source files retained their hashes
and modification times, with empty staging. The run started with 92,406,534,144
bytes free and ended with 175,344,197,632 bytes free; its test artifacts occupied
672,728,833 bytes. Those free-space readings include other activity on the drive;
this continuation performed no cleanup.

The runner invoked this bounded suite with `-v --tb=short --maxfail=3`:

```powershell
if ((Get-PSDrive -Name C).Free -lt 40GB) { throw 'Less than 40 GiB free' }
$taskBase = 'C:/Users/matri/.codex/tmp/ae-' + [guid]::NewGuid().ToString('N').Substring(0,8)
if (Test-Path -LiteralPath $taskBase) { throw 'Test base must be fresh' }
& .venv/Scripts/python.exe -X utf8 -u -m pytest -v --tb=short --maxfail=3 `
  tests/test_semantics20_unlisted_sales.py tests/test_semantics20_property_sales.py `
  tests/test_semantics20_estate_securities.py tests/test_semantics20_estate_administration.py `
  tests/test_semantics20_estate_cases.py tests/test_semantics20_succession.py `
  tests/test_semantics8_foundations.py tests/test_semantics8_causal_membership.py `
  tests/test_research_export.py tests/test_recorded_replay_golden.py `
  tests/test_participant_mode.py tests/test_external_agent_gateway.py --basetemp $taskBase
```

All 76 changed/new Python files passed AST and whitespace checks. Normal
`git diff --check` passed; frozen migrations through v024 and hash contracts
through v6 remain unchanged. Only the existing Starlette/httpx deprecation
warning appeared. Full Python CI shards and the release gate remain publication
requirements. The earlier 294- and 68-case property results predate the new
private-share mechanism; the 219-case result above covers the final source.

The documentation check subsequently passed **22 tests / 0.53 s** using fresh
base `C:/Users/matri/.codex/tmp/ae-1abd29a8`, with 1,080 unchanged source files and
empty staging. Receipts use
`tmp/estate-legal-representation-unlisted-sale-documentation-direct`. The first
documentation launch did not start pytest because the temporary runner was no
longer present; the successful check invoked pytest directly with the same
40-GiB admission and source-freeze checks. At that point the earlier mechanics
and four-case world metadata files were also no longer present. Their prefixes
above are historical receipts; the completed 219-case log, metadata and source
snapshot remain available. Only this specification and the execution log changed
after that integrated run.

### Implemented late claims and completed distributions

Each Semantics-20 estate and its opening event now record
`prospective_receipts_no_clawback_v1`. Completed cash, title and share
distributions remain final. A newly admitted claim can reach assets still
retained by that estate and actual future same-currency receipts. Existing
claims and reserves retain their priority; heirs and later buyers do not become
personal debtors. This is the simulation's declared research policy.

The implementation adds one immutable `distribution_finality_policy` column to
`estate_cases` and checks it against the opening event. The unpublished schema
remains 25 with 43 succession tables; hash-v7 now records inventory hash
`f3a8f1f80977a876d474b70d12a0848e4622ee3d1b40f3eeac919426a8aaefe3`.
Frozen migrations through v024 and hash manifests through v6 remain unchanged.

Existing receipt admission cutoffs and property/security release frontiers
already distinguish claims and reserves admitted after a completed transfer,
including within one tick. The tests verify those boundaries directly; no new
admission journal or duplicated disposition history was needed. Actual later
cash still passes through the existing ledger, claim and reserve processors.

`EstateCases.finality_at` provides a read-only end-of-tick snapshot of the policy,
completed opening inventory, outstanding claim face amounts by currency,
unresolved disputes and retained property/security lot counts. It excludes
future admissions, collections, dispute resolutions and asset releases. An
opening inventory record does not imply that later claims are impossible. This
is the reporting foundation; household beneficial positions and their city
presentation remain the next work.

`tests/test_semantics20_estate_finality.py` now has thirteen cases. They cover
same-tick receipt/admission order; later claims after in-kind and funded property
and private-share transfers; claims against retained assets; subsequent
beneficiary death; separate currencies; failed/duplicate admission; immutable
policy and original distribution evidence; and historical, read-only status.
A combined case sells property, admits a later claim while company shares remain
retained, then sells those shares for real cash to repay both bank claims and
the award. The earlier property's title stays unchanged.

The four-day world case uses a declared owner death, late claim, independent
official decision and funded contract performance. Earlier cash inheritance and
share movements remain unchanged, while later estate cash pays the actual award.
Daily restarts, nonempty export, exact recorded replay, no replay provider calls
and an unchanged stored source file passed. These controlled decisions do not
establish emergent claimant/buyer behavior or biological cohort evidence.

Development receipts: the baseline had **2 passes and one missing-policy failure /
1.87 s** (`tmp/estate-finality-baseline`, base `ae-3262d081`). The first expanded
run had **28 passes and two currency-fixture failures / 27.49 s**
(`tmp/estate-finality-mechanics`, base `ae-eb37a2b3`). The property profile uses
NSD, while the generic test helper creates a USD checking account. A subsequent
three-case attempt exposed that destination-wallet mismatch and incorrectly
expected a retained-lot release for a direct inheritance
(`tmp/estate-finality-property-and-world`, base `ae-793a70ff`). The fixtures now
use the actual currency and the direct share-movement journal.

The corrected property pair and world case passed **3 tests / 96.64 s**
(`tmp/estate-finality-funded-world`, base `ae-99239e0f`). The combined property/
retained-share case passed **1 test / 1.36 s** (`tmp/estate-finality-mixed-assets`,
base `ae-f5101679`). All bases are under `C:/Users/matri/.codex/tmp/`; receipt
prefixes have `.log`, `-meta.json` and `-source.json` files. All 1,081 source files
kept their hashes and modification times during each run, with empty staging.
Production code did not change after the first expanded run.

The final affected regression passed **136 tests / 548.85 s**, including all
thirteen finality cases, existing estate cash, disputes, awards and listed
securities, Semantics-19 cash behavior, schema foundations, research exports and
golden recorded replay. Receipts use `tmp/estate-finality-integrated` with fresh
base `C:/Users/matri/.codex/tmp/ae-b2a88416`. All 1,081 source files kept their
hashes and modification times; staging stayed empty. The run started with
173,696,139,264 bytes free and ended with 172,785,680,384 bytes free; test artifacts
occupied 378,705,499 bytes. Only the existing Starlette/httpx warning appeared.
AST/whitespace and normal diff checks passed; frozen migrations/hash contracts
remain unchanged. Full Python CI shards and the release gate remain publication
requirements.

The bounded command was:

```powershell
if ((Get-PSDrive -Name C).Free -lt 40GB) { throw 'Less than 40 GiB free' }
$taskBase = 'C:/Users/matri/.codex/tmp/ae-' + [guid]::NewGuid().ToString('N').Substring(0,8)
if (Test-Path -LiteralPath $taskBase) { throw 'Test base must be fresh' }
& .venv/Scripts/python.exe -X utf8 -u -m pytest -v --tb=short --maxfail=3 `
  tests/test_semantics20_estate_finality.py tests/test_semantics20_estate_cases.py `
  tests/test_semantics20_estate_disputes.py tests/test_semantics20_legal_awards.py `
  tests/test_semantics20_estate_securities.py tests/test_semantics19_estate_cash.py `
  tests/test_semantics8_foundations.py tests/test_research_export.py `
  tests/test_recorded_replay_golden.py --basetemp $taskBase
```

Documentation verification then passed **22 tests / 0.37 s** with 1,081 unchanged
source files and empty staging. Receipts use `tmp/estate-finality-documentation`;
fresh base `C:/Users/matri/.codex/tmp/ae-cd938a32`. Only this specification and
the execution log changed after the final integrated run.

### Household position acceptance contract

Build one selected-tick, per-currency position inventory before aggregating
households. Each position needs a stable instrument/source key, original holder,
current legal or nominee holder, unit, amount and evidence. Keep spendable cash,
restricted cash, outstanding receivable face amounts, debts, observed market
marks with their date, and unpriced residual rights distinct. Use ledger history,
membership intervals and immutable claim/disposition journals; today's balances,
membership or loan status cannot stand in for historical evidence. Add a minimal
recorded transition where an existing source cannot reconstruct the required
historical amount.

`residual_people_at` identifies residual beneficiaries but returns a
set of people and discards allocation weights. Household reporting must instead
follow exact beneficiary fractions through recorded estates, preserving creditor
priority at every step. A contingent residual is not unconditional ownership of
the entire nominee balance. Keep source/lineage links when a judgment replaces
an obligation or wage claim, and count the outstanding underlying right once.
Apply the finality policy and historical status above when a later receipt or
death changes the residual path.

`Metrics._gini` currently sums all accounts for living citizens, while the metric
registry calls it cash inequality. Implement a separately defined cash measure
with explicit wallet kinds, population, per-currency treatment and zero/negative
balance convention. Version its engine emission and research-reader definition
together and preserve old stored values/replay. `Metrics.snapshot` already
supports named series; update the catalog/reader and relevant city displays so
users can distinguish the corrected cash measure from the historical series.
An unpriced asset or unsupported currency conversion must not become zero wealth
or an invented market mark. Cash inequality and the complete position inventory
are separate acceptance requirements.

Test two heirs sharing one nominee claim, successive estates with intervening
creditors, claim replacement/partial payment/loss, currency separation,
historical membership and death boundaries, and observed versus unpriced assets.
Reconcile source totals and fractions before household aggregation. Follow with
authorized selected-tick city presentation, repeated/cohort succession and the
true multi-decade campaign. This step remains W5; W6–W9 and equal goods/equity
research coverage still require completion.

## Current acceptance and publication gates

The [W5 acceptance audit](2026-09-09-w5-acceptance-audit.md) is the current
requirement map. The earlier implementation sections preserve their observed
results and limits; an old sequencing note does not make a subsequently
implemented mechanism unfinished again.

The current supported paths include custody and funded disposition of retained
securities/property, original-funder refunds, independent legal decisions,
consenting representation, retained financial rights, prospective-receipt
finality and per-currency household positions. Assets with no funded buyer or
qualified representative remain explicitly retained or pending. That is the
declared policy, not permission to invent a price, new officials or heir debt.

The combined cohort regression now includes two original personal projects,
simultaneous owner deaths, later guardian/successor death and an actual receipt
through two estates. It preserves exact title fractions, original contribution
accounts and transaction links, distinct currencies, original identities and
historical reports. Three variants passed with export and exact recorded
replay. This controlled four-day case does not establish native generations.

The remaining gates are:

1. Complete the fixed native campaign and its final cohort audit. It is paused
   at day 7,667 of 14,600. Preserve newborn identity/aging, care gaps,
   formation/dissolution, retirement/death, estate outcomes and equal goods/
   equity observations; then validate the full source-preserving replay/export.
2. Implement and verify the external population boundary required by S5.
   Scheduled arrivals and internal moves exist; the current global census
   has no external-departure term or distinct departure wealth/commitment
   settlement. Keep that gap explicit and preserve the current closed-world
   semantics. Follow the contract in the acceptance audit.
3. Run the complete supported-inventory and current-version integration gate,
   including rejection, rollback, simultaneous/repeated succession, currency,
   principal/title/share conservation, current authority, selected-tick privacy,
   additive migrations and exact historical replay. Focused receipts do not
   replace full CI shards or the release gate.
4. Preserve the supported long-only ownership boundary. Short selling, leverage,
   derivatives and external execution retain the original S8 deferral. The
   research reader must continue separating realized cash, outstanding face
   claims, executed-price marks and unpriced contingent rights; neither
   legacy account inequality nor cash Gini is total net-wealth inequality.
5. Publish/freeze the development semantics and hash contract only after the
   full applicable contract is proved. W6 education, W7 production/housing/
   spatial mechanics, W8 banking/credit and W9 calibration/scale remain open
   under the original ordered goal.

Use fresh short pytest directories and check for at least 40 GiB free before
each run. Keep source, documentation, staging, commits and builds unchanged
while scientific tests run. Preserve the current native campaign's frozen
sources, harness and declared resource limits. No paid providers, additional
cleanup or merges are required for these local checks.

## Implemented household positions and cash inequality

`research.household_positions.household_positions(store, tick=...)` now returns
`household-instruments-v1` for a committed Semantics-20 tick. It is a private
operator/research reader, without a public route. It rejects future, active,
invalid and incompatible boundaries. It never opens a writable source or
repairs missing historical evidence.

The instrument inventory contains one source key for each cash account, earned
wage claim, judgment, monetary contract obligation, personal bank principal,
shareholding and personal construction-project interest. Household and estate
views reference those keys. Original/nominee holders, counterparties, currencies,
units, evidence and claim replacements remain explicit. Per-currency subtotals
separate signed wallet cash, restricted cash, receivable face amounts, debt face
amounts, observed equity marks and unpriced rights. There is no currency
conversion or invented net-wealth scalar. A face claim is not an estimate of
collection, and an old execution mark is not guaranteed sale proceeds.

Cash comes from ledger entries at or before the requested tick, not the cached
account balance. Primary membership and death intervals place a holder in the
correct historical household or estate. Zero-entry account identities are not
exposed before a recorded entry. Earned wages reconcile accruals, gross payments,
losses and dated novations against the historical receivable account. Judgments
use their recorded credits, payments and losses; a replaced obligation has zero
remaining face value, while any unadjudicated wage interval remains separate.
An obligation with an undated unsupported disposition is explicitly unavailable.

Personal loan principal uses the existing exact `loan <id> payment` transaction
reference and the lender reserve leg, which excludes interest. A recorded
default ends the original personal loan; an admitted estate claim replaces it
using the same instrument key. Estate payments and releases reduce that claim;
a bank's accounting loss does not discharge an estate's continuing obligation.
Firm borrowings are not personal debts of its shareholders.

The share-history audit found no original issuance quantity in the founding
event and no ordinary trades in `share_movements`. Under Semantics 20,
`Firms.found_firm` now records `founder_issuance`, including an explicit zero-unit
issuance. The reader combines that record with transfers, actual trades,
funding-round records, distinct `vc_funded` events and IPO issuance records.
This prevents a funded pitch and its typed funding round from being counted
twice. Bankruptcy ends recorded share quantities at its dated boundary. The
latest reconstruction must reconcile with the committed cap table. Historical
property fractions reconcile to one title; construction cost is never used as
an observed market valuation.

There is no new schema column or table in this step. Schema 25, the 43 succession
tables and the current hash-v7 schema inventory remain unchanged at
`f3a8f1f80977a876d474b70d12a0848e4622ee3d1b40f3eeac919426a8aaefe3`.
The issuance journal and new metric emission extend the still-unpublished
Semantics 20. Older unpublished Semantics-20 artifacts without issuance evidence
are rejected by this reader rather than reconstructed from today's float.
Regenerate a disposable fixture under the current source; preserve old source
runs. Frozen semantics and manifests are unchanged.

Each estate view exposes creditor order, currency, remaining face amounts,
unresolved reserves and the obligations protected by those reserves. A reserve
is not added again as admitted debt. Beneficiaries receive exact rational
fractions of the residual. A path through successive estates retains every
intervening creditor/reserve boundary. Household contingent-interest rows carry
no unconditional monetary amount and do not copy nominee assets into several
heirs' additive totals. Evaluate each boundary in the currency of actual
receipts. These are recorded conditional rights, not a full-collection scenario
or a forecast of future estate receipts.

`Metrics.snapshot` preserves the old `gini` values and additionally emits
`cash_gini:<currency>` and `cash_population:<currency>` for Semantics 20.
`engine.position_history.cash_distribution_at` uses checking, savings and FX
wallets only. Every living registered citizen, including minors and citizens
with no wallet in the selected currency, contributes an observation. It nets
wallets per person/currency and clips negative net balances only for the Gini
formula. The report retains signed and negative cash totals. Empty and
zero-total cohorts have zero Gini by explicit convention, alongside the
population count. Neither this citizen measure nor the historical series is
household net-wealth inequality.

The registry is `research-metrics-v2`. The unchanged historical `gini` is now
described honestly as `legacy-all-account-gini-v1`; its old cash label was
incorrect. New series use `citizen-wallet-cash-gini-v20` and
`citizen-wallet-cash-population-v20`. Strict readers reject unrecorded currencies,
incompatible semantics and uncommitted ticks. No old metric row is rewritten.

### Reporting verification

The new file has 22 focused cases. These cover historical cash/currency/origin
boundaries; negative and empty populations; metric semantics; invalid reads;
principal repayment and default; two heirs sharing one wage claim; successive
estates with separate creditors; taxed partial collection, novation and loss;
contract judgments and segregated reserves; changing household membership;
foreign debts; actual share execution dates; whole and fractional property;
missing issuance evidence; cap-table mismatch; and both funding paths.

Initial verification passed 14 cases and found three failures: missing founder
and trade histories, and a fixture attempting an award loss before actual
bankruptcy. The first corrected run passed nine cases and rejected three old
payroll-only employer fixtures lacking any issued cap table. Those fixtures now
create actual companies. The subsequent run passed **27 tests / 133.45 s**,
including all registry cases and a four-day world with daily restarts, export,
exact replay, identical historical position reports and an unchanged source
database. This is a controlled four-day case, not multi-decade/cohort evidence.

The expanded regression passed **225 tests / 841.14 s** across positions,
registry, finality, estate cash/listed and private securities, earned judgments,
Semantics-19 cash compatibility, credit, company funding/IPOs, schema foundations,
research export and golden replay. Receipt prefix:
`tmp/estate-finality-household-positions-integrated`; fresh base:
`C:/Users/matri/.codex/tmp/ae-899ef326`. All 1,084 source files retained identical
hashes and modification times, with empty staging. Free space moved from
172,045,434,880 to 170,889,494,528 bytes; test artifacts totalled 623,459,061 bytes.
Only the existing Starlette/httpx deprecation warning appeared.

The final funding-path pair passed **2 tests / 1.56 s** with unchanged source and
empty staging. Prefix: `tmp/estate-finality-household-funded-issuance`; base:
`C:/Users/matri/.codex/tmp/ae-4c9685d3`. Only that test pair was added after the
expanded regression; production code did not change. Syntax and whitespace
checks passed for all 81 changed/new Python files. Full CI/publication gates
remain pending.

Documentation verification passed **22 tests / 0.48 s**, with all 1,084 source
files unchanged during the run and empty staging. Prefix:
`tmp/estate-finality-household-documentation`; fresh base:
`C:/Users/matri/.codex/tmp/ae-e53d98d1`.

### Next implementation from this checkpoint

The local operator presentation and currency-labelled cash inequality are now
implemented in the [financial inspector](2026-09-08-household-financial-inspector.md).
Its route preserves the public household layer, applies selected-day identity
visibility and omits raw account references and unrelated households. External
actor financial access remains outside this local operator contract.

1. Extend combined estate, household and financial stress to simultaneous
   losses, multiple original owners, repeated generations and sustained native
   policies. Keep current complete source journals/reconciliation as acceptance
   criteria; do not bypass missing history with mutable balances or float.
2. Run the true multi-decade campaign with explicit storage/checkpoint limits,
   a fresh short test base and at least 40 GiB free before every pytest run.
   Profile the historical ledger scans and estate-path growth before claiming
   large-world reporting performance. Keep source/docs/builds unchanged while
   scientific tests run. W6–W9 and equal goods/equity validation remain open.

The [native life-course validation protocol](2026-09-08-life-course-validation.md)
now records the one-year pilot, physical origin-lookup optimization, 64 passing
regressions and exact 365-day recorded replay. The declared forty-year campaign
uses ten-minute resumable segments and a 16 GiB artifact allowance, preserving
a 40 GiB free-space reserve. These measurements and the three-day resume/replay
smoke do not satisfy the multi-decade criteria.

The same campaign has reached a clean pause at day 7,667 (about 21 years), with
seven births, eight deaths/estates and eight retirement events. All 21 annual
household reports reproduce from the closed source, and 7,668 census rows
reconcile. Person 26 reached adulthood on day 7,563 after eighteen ordinary
birthdays; no endowment was granted. All seven native partnerships' recorded
consent is independently checked. Child 28 died of recorded illness at sixteen,
while child 27 remains without a guardian. The care gap is recorded separately
from the current health hazards. School enrollment remains W6. The fixed horizon,
complete estate-inventory audit and full campaign replay/export remain open; see
the [bounded verification specification](2026-09-09-campaign-replay-and-export.md).

`tests/test_semantics20_combined_cohorts.py` now verifies simultaneous deaths
of two original owners, later loss of the surviving guardian/heir, and an
actual delayed contract payment through successive estates. The domestic case
preserves distinct issuer shares, exact residual fractions and both creditor
boundaries, with daily restarts, historical reports, export and exact replay.
It passed in 69.76 seconds, without production changes or source mutation.
The same combined case now also retains an unpaid 70-cent EUR estate claim
without converting the later USD receipt. Both currency variants passed in
125.00 seconds. `tests/test_semantics20_age_boundaries.py` adds two declared
genesis cohorts that advance daily through a guardian's death before/on the
18th birthday, cancellation of an obsolete joint move, and retirement at 65.
Both 22-day cases passed in 573.99 seconds, including daily restart/history,
export and exact replay. The former guardian loses company control while the
new adult retains the shares. These explicit stress cases do not prove native
multi-generation behavior; retain that distinction in the full W5 acceptance
audit. Evidence and fixture correction are recorded in the life-course plan.
The combined regression now includes actual funded personal projects and a
completed home through both original-owner deaths and the successor's estate.
All three variants passed in 187.48 seconds. The current acceptance audit above
replaces the older sequencing checklist and retains external departure as an
unimplemented population boundary.

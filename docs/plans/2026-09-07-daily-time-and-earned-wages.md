# W5/W6: daily time, delivered care and earned wages

Status: implemented and locally validated; committed CI results are tracked on
draft PR #82 and in the parent execution log.
This slice implements the time constraint
needed by household care and education. Full estates, cohort validation and the
remaining W6–W9 requirements remain part of the parent roadmap.

## Clock and scope

Semantics 18 is an explicit opt-in. Semantics 1–17 retain their current behavior.
Schema 23 is additive; its authoritative state gets hash-contract-v5. Existing
hash contracts are frozen, and replay never upgrades its source recording.

Each living person gets one daily time budget. The initial research baseline
allows 960 activity minutes and reserves the other 480 minutes for rest. These
are declared model assumptions, not calibrated sleep or demographic estimates.
Every time allocation belongs to a person/day and has committed and delivered
minutes. Allocations cannot exceed the day's budget. Work and delivered care
are mechanical effects of an accepted standing plan; an appointment reservation
does not prove that the person attended.

Opening health, mortality, births and residence changes resolve before the
Semantics-18 time allocation, payroll and production. City routines use the
resulting population and places. Earlier versions preserve their phase order.
Plans submitted during EXECUTION take effect the following day, so an agent
cannot retrospectively replace work already performed with childcare or study.

## Household care and personal plans

- Existing child-care requirements become a daily demand with recorded delivery
  and shortfall. Required care is never reported as delivered merely because a
  guardian exists. Caregiver and recipient each spend the delivered care time.
- A living adult may submit a standing work/childcare plan. Explicit offers can
  name current minor household members; a declared primary-wards selector can
  follow the actor's current guardianship. Named offers do not extend themselves
  to newly born or newly assigned children.
- Explicit care offers settle first in stable order, then the default primary
  guardian supplies remaining care. One child's demand cannot be satisfied more
  than once. Care and a person's other commitments compete for the same minutes.
- The default plan gives care priority and targets one ordinary 480-minute work
  day. Scarcity reduces work or leaves a recorded care shortfall. Models can
  choose a different feasible work/care plan; this is an economic tradeoff,
  not a claim that a particular household preference is empirically correct.
- Separation, death, adulthood and moves revalidate care targets each day.
  Ineligible targets receive no delivery. Children cannot submit adult plans.

## Work, study, construction and travel

An employee works only for an eligible active employment; an owner can allocate
work to an eligible owned firm. One person's total allocation is shared across
all firms, preventing one founder from supplying a full worker to several
companies on the same day. Actual minutes determine wage accrual and production
capacity. A carried sub-unit production remainder prevents systematic loss from
rounding fractional worker-days; it cannot bank whole unproduced units.

Study and construction consume minutes only when their existing economic action
succeeds. A failed action rolls back time, money and progress together; retries
cannot buy progress without spending time or charge the same receipt twice.
The initial coefficients are 120 minutes per skill study and 60 minutes per
construction work unit. Existing civic appointments reserve one 480-minute
business period; attendance records delivery against that reservation.

The baseline declares fixed travel burdens: 60 minutes for a work/appointment
journey and 480 minutes for a regional relocation. These are neither measured
routes nor distance-derived accessibility benefits. Detailed transport and school
schedules remain W6/W7 work. Relocation and existing civic commitments reduce
time available for care, work and study; simultaneous activities are not counted
as if they occurred sequentially outside the 24-hour day.

## Wages and accounting

An employment's stated period wage is earned in proportion to actual work:

`daily numerator = period_wage_cents * worked_minutes + carried_fraction`

`denominator = contractual_pay_interval_days * normal_workday_minutes`

Whole cents accrue through the ledger from a firm wage-payable account to an
employee wage-receivable account. The fractional remainder carries forward.
These are non-cash claims, never bank deposits or spendable checking balances.
Daily accrual records, the outstanding claim and both ledger accounts reconcile.

On payday or after employment ends, actual payment moves firm cash, releases the
payable/receivable pair and credits the beneficiary's same-currency cash account,
with the existing income-tax rule. Insufficient cash leaves an explicit unpaid
claim; money is not invented and the claim is not silently erased. Final firm
bankruptcy records any residual write-off through the ledger. A full contractual
period of unpaid wages precedes the existing cash/debt insolvency rule; this is
a declared grace-period assumption. Bankruptcy pays senior bank claims first,
then available residual cash to wage claims in employment order, and records
uncollectible wages explicitly. It is not a jurisdiction-specific priority model.

Death transfers a wage claim as a claim to the recorded heir or government.
It cannot convert an unpaid receivable into inherited checking cash. Historical
employment identity remains unchanged while the claim's beneficiary is recorded.
The existing general heir/estate policy remains a limitation pending full W5
estate settlement and business succession.

The city household inspector shows delivered and unmet care only from the
selected day's records, within the existing visible-member boundary. Earlier
semantics keep their unavailable/pending delivery status. Private time plans and
non-cash wage claims are available in the actor's decision context; the participant
catalog offers bounded next-day plans. Scripted guardians use the declared
care-first baseline; this is not inferred model or human preference.

## Acceptance evidence

City positions remain coarse fixed-slot projections. A routine business lease
does not prove delivered work; daily allocations are the source for actual work
and care minutes. Detailed routes and minute-by-minute location remain W7.

- Daily allocations reconcile to the configured available minutes; the same
  person cannot work full days at multiple firms.
- Care demand, delivery and shortfall reconcile without duplicate coverage.
  Explicit household care sharing can release the guardian's time for work.
- Known-answer days/periods prove that childcare changes actual earned wages and
  physical output, including fractional cents and output capacity.
- Illness, retirement, death, new employment, job loss, migration and a changed
  care target use their actual daily boundaries.
- Failed/repeated study or construction is atomic across time, cash and progress.
  Appointment reservation and actual attendance remain distinguishable.
- Wage accrual, partial/final payment, tax, inheritance and bankruptcy reconcile
  per currency; claims never enter money/deposit totals or become cash on death.
- Native/scripted/model/external action context exposes the same feasible plans
  and time evidence. A real scripted household rehearsal resumes and replays
  exactly, with an unchanged source, then exports its authoritative records.
- Existing Semantics 1–17 replay and hash contracts remain covered. Fresh short
  test directories, disabled rehearsal checkpoints and a 40-GiB free-space guard
  bound local validation; complete Python coverage belongs in CI shards.

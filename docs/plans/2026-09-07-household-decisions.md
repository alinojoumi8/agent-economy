# W5: mutual household decisions

Status: implemented; verification is recorded in the execution log. This is a dependency of the remaining W5
care, estate and long-horizon work; it does not complete W5 or the research plan.

## Behavioral contract

Semantics 17 adds recorded partnership and household-move proposals. Semantics
1–16 retain their recorded behavior. Schema 22 is additive and does not infer
partners or consent in existing recordings.

- A living adult citizen can propose a partnership to another known, unrelated
  adult in the same region. Neither may have an active partner. Every adult in
  both households must assent before their residences are combined. Proposing
  records the proposer's assent, not anyone else's.
- Terms bind the exact membership, guardianship and region being considered.
  Birth, death, adulthood, separation or another move invalidates those terms.
  Rejection, expiry and cancellation are recorded. Duplicate submissions have
  actor-scoped keys and cannot create a second relationship or residence change.
- Partners retain personal accounts, companies, property and other assets.
  Household formation changes residence and relationship history only. Care
  needs remain distinct from care actually delivered.
- An adult can separate without a partner's permission. Their current primary
  minor wards accompany them; custody is reconciled only after all membership
  changes. This is an explicit first custody policy, not a model of family law.
- A joint move requires a qualified wage opportunity for its proposing citizen
  and recorded agreement from every adult in the household. Other adults can
  accompany the proposer, explicitly leaving current employment. All members
  must have no active credit exposure. Children accompany their household and
  cannot issue independent adult actions.
- An agreed move settles atomically at night, after mortality and individual
  migration. Current membership, guardianship, employment and credit conditions
  are checked again. Every member and the household move together, or none do.
  Existing currency balances stay in their original wallets; destination
  wallets receive no invented wealth or automatic FX conversion.
- Proposals and assents enter canonical replay. Private pending proposals appear
  only in an affected adult's decision context. Scripted citizens and model
  citizens use the same actions and facts; a scripted matching policy is a
  declared baseline, not evidence that a model autonomously chose a partner.

## Implementation and acceptance

1. Add migration, strict commands and deterministic proposal/assent mechanics.
2. Connect household membership, custody, death, regional migration and city
   residence. Preserve atomic changes and exact historical semantics.
3. Supply bounded private decision context and a declared scripted matching
   baseline, plus action documentation for model and external citizens.
4. Verify mutual assent, refusal, expiry, stale terms, duplicate submissions,
   unauthorized/minor actors, kinship rejection, separation with children,
   death before settlement, money/asset conservation and transaction rollback.
5. Run a small real scripted-agent handshake and exact recorded replay, with
   fresh temporary runs, checkpoints disabled and at least 40 GiB free space.

The opt-in profile is `runs/household-decisions-rehearsal.yaml`. Its declared
scripted baseline proposes a known social contact on its configured formation
cadence, accepts still-valid partnership offers and declines a joint move that
would end the companion's existing job. These are explicit research assumptions.
`scripted_matching: false` disables that matching/assent baseline; model and
external citizens still receive the permitted actions and recorded terms.
Partnerships involving shared recorded ancestry are refused. Mutual proposals
are limited to 128 members; an adult can still separate from a larger household.

Schema 22 adds `household_decisions`, immutable `household_assents` and
`partnerships`. Hash-contract-v4 classifies them as authoritative; v1–v3 contract
files remain unchanged and cannot omit populated family-decision state. Exact
replay of pre-17 semantics ignores only these named extension tables when empty
and the version-22 migration receipt. A schema-21 source is replayed without
upgrading or rewriting that source; populated extension tables are compared.

## W5 work still required

Care needs must become delivered care with a finite work/study/travel/care time
budget. Wage accrual and production must reflect that budget without charging
only the payroll day or counting a founder's time in multiple firms. Estates
must settle every currency, bank loss, security and business/project interest
with explicit heir and management succession. Cohort checks and an actual
multi-decade provider-free run remain required. W6–W9 remain in the parent plan.

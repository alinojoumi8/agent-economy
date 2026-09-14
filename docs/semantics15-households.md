# Persistent people and household needs

Semantics **15**, schema **21**, demographic model description
**agent-economy-demography-v1**. This is the first W5 implementation checkpoint.
The [status ledger](implementation-status.md) records release maturity; the
[research city specifications](plans/2026-09-06-research-city-specs.md#s5-people-households-and-generations)
retain the full delivery contract.

The [City evidence household lens](plans/2026-09-07-city-society-lenses.md) now
reads these historical records. It exposes core members and their exact-day
child needs, with explicit partial visibility and unavailable data. This
observer feature does not complete the remaining W5 economic mechanics.

## Run the bounded mechanics rehearsal

```powershell
.\.venv\Scripts\python.exe run.py --config runs/household-rehearsal.yaml --ticks 3
```

The inherited profile uses the scripted provider. Its fixed genesis contains
14 citizens and 10 institutional actors. A declared birth intervention for
person 11 at day 1 exercises the child path in a short run. Natural birth
hazards are zero in this profile, and `population_mode: drift` disables adult
replacement. This is a synthetic mechanics fixture, not a calibrated forecast.

Existing profiles keep their selected semantics. Select version 15 in a fresh
configuration; do not edit an existing run's stored semantics marker.
Historical behavioral/spec-closure genesis mutation fixtures are rejected in
version 15 because they do not declare the new person origins.

## Identity, time and households

`person_lifecycle` extends the existing `agents.id`. It records immutable
origin, origin tick, birth tick, birth key and legacy dependent count, plus
current life stage and death tick. Person records cannot be deleted, so a dead
person's ID cannot be freed and reused. Parent/child relations remain after
death or a change of guardian.

Genesis creates one household per existing actor. No named children, spouses
or shared assets are inferred from the old `dependents` number. An initial
actor's synthetic age basis is explicitly recorded: with ID `i`, age `a` and
entry day `t`, birth day is `t - 365*a - ((365-i%365)%365)`. Newborns instead use
their actual birth day. Age is `floor((day-birth_day)/365)`; their first birthday
is exactly 365 days after birth. School-age begins at 6 and adult eligibility at
18. School-age is not evidence of enrollment. Retirement uses the configured
retirement age and the existing employment/cadence transition.

A birth atomically creates the child, zero-balance personal checking account,
membership, parent relation, primary guardianship and birth event. The key
`birth:<day>:<parent ID>` permits one birth per parent/day and makes retries
idempotent. A birth cannot follow the parent's death earlier in the same tick.
A newborn's public label uses the permanent person ID and remains appropriate
after adulthood. Parentage stays in the explicit relationship records instead
of being embedded in the public name.
There is no arrival wealth, housing charge, adult persona call, job assignment,
compute grant or increment to the parent's legacy `dependents`.

Children use deterministic needs. They receive no scheduled adult decisions,
adult arrival enrichment or model conversation/weekly-reflection calls.
Independent actions are rejected except `do_nothing`; the labor engine also
rejects child applications and hiring. At adulthood they keep their identity,
personal assets and household, close primary guardianship and become eligible
for ordinary decisions. The transition grants neither wealth nor a job.

Membership intervals preserve joins, departures and role changes; a database
constraint permits at most one active primary household per person. Death
closes membership and care assignments. An empty household dissolves. A
remaining minor stays in the household; the lowest-ID living adult member is
the deterministic successor guardian. Without such a member, custody remains
unassigned and daily care/food gaps are recorded. Guardian appointment itself
transfers no ownership or money.

The engine's adult separation operation opens a new single-person household
and preserves the earlier interval. Existing individual regional migration uses
this same separation rule after regional settlement. Children and property do
not silently relocate with that adult. This can leave an explicit care gap.
Joint family migration and accepted partnership formation remain pending.

When civic places are enabled, members share the household's original district
anchor. Children remain at its routine home during all three daily slots.
These are city presence records, not a housing title or a school placement.

## Child demand and money

The declared policy is `guardian_basic_needs_v1`. After adult action execution,
at the start of `MARKET`, it visits living children in ascending ID order. For
each child's requirement, it considers available firms in the configured
sector, child's region and guardian wallet's currency. Sellers are ordered by
posted price then firm ID. Ordinary `Firms.buy_goods` settles affordable units,
decrements inventory and records the goods sale and balanced ledger transfer.
Every purchase is paid from the guardian's personal checking account.

Decision context exposes the actor's own household, responsible children,
requirements and previous-day spending grouped by currency. Parent/guardian
support events feed ordinary memory. Other families' support details are not
exposed through this context. The policy's automatic market timing is stated
explicitly, so an actor need not infer why its balance changed.

`child_needs` records required/purchased units, spending and currency, actual
seller allocations, responsible guardian and care requirement. Unaffordable or
unavailable units remain unmet; no substitute supply, borrowing, FX conversion
or public subsidy is invented. A unique child/day row and phase savepoint make
retries safe. Personal balances and beneficial ownership remain personal.

The old dependent count continues through the old actor policy. Explicit
children are not added to that count, so the two representations cannot both
independently count the same new child. Legacy counts remain an uninstantiated
aggregate and are separately reported in the census.

| Setting under `households` | Default | Contract |
|---|---|---|
| `child_goods_units` | 1 | Integer 0–100 per child/day |
| `goods_sector` | `food` | Exact sector name, 1–40 characters |
| `care_minutes_per_child` | 120 | Integer 0–1440 required minutes/day |
| `scheduled_births` | `[]` | At most 1,000 unique `{tick, parent_agent_id}` entries; positive integer values |

These are explicit research assumptions. Scarce food is allocated by child ID,
and adult action purchases occur first; that priority is not a fairness claim.
Care minutes are **requirements only**: `time_allocation_pending` means a
guardian exists but delivery is unmeasured, `unassigned` means none exists, and
`not_required` means the configured requirement is zero. No work or study time
has yet been displaced. Do not interpret this checkpoint as completed childcare.

## Randomness, census and replay

Version 15 demographic draws use the SHA-256 key
`["demography_v1", seed, mechanism, day, person ID]`, serialized as compact ASCII
JSON. The top 53 bits of its first eight bytes yield a draw in `[0,1)`.
Mortality, illness onset, sick/critical transitions, birth and replacement delay
have separate mechanism names. Adding a child or changing another person's
health branch cannot consume that person's later demographic draws.
Legacy versions retain their sequential lifecycle PRNG exactly. Other world
mechanisms still have sequential streams; the broader keyed-randomness research
contract is not complete.

`population_census` records every completed day and checks:

```text
closing population = opening population + births + adult arrivals
                     + other engine-created people - deaths
```

The day-zero population is the declared initial roster. `arrival` is a funded
external entry; `engine_created` separately labels later institutional
replacement actors. Cross-region moves do not alter global population.
`stable` replaces adult deaths only, and can still grow through births;
`drift` creates no automatic replacement. An externally scheduled adult arrival
remains separate from fertility. International departure/open-migration policy
and full population calibration remain pending.

The census also records active households, unassigned minors and surviving
legacy dependent counts. Completed days require a preceding census and cannot
rewrite an existing count. World reconciliation checks age, life/death state,
active membership, residence and guardianship as well as the ledger. The new
tables participate in canonical replay comparison. Migration adds empty tables
to old writable stores without inventing families or altering old mechanics;
source replay databases remain read-only.

Research hashing/default export selects **hash-contract-v3** for Semantics 15
and includes all seven household tables. The v1 and v2 manifest files and their
schema inventories remain unchanged for historical sources. They tolerate the
known new tables only while those tables are empty; populated household state
or a version-15 run cannot be hashed/exported through a contract that omits it.
An additive writable-store migration still changes its schema/history metadata;
it is not a claim that the migrated database has the old byte or research hash.

## Verification and remaining W5 work

[The focused suite](../tests/test_semantics15_households.py) covers interrupted
birth and purchase rollback, duplicate handling, primary membership constraints,
origin immutability, guardian death/succession, separation, census corruption,
age thresholds, minor action/work exclusion, real inventory shortfalls, shared
city residence, adult-only replacement, and birth/resume/recorded replay.
The suite runs in the required CI core job alongside historical contracts.

This checkpoint retains the existing estate waterfall: strongest living social
tie, then government when none exists. It does **not** implement the planned
family inheritance shares, explicit asset/creditor inventory, minor-asset
custody authority, project/housing succession or full bank-loss accounting.
Guardian reassignment is not inheritance. Also pending: partnership assent,
joint family migration, care commitments and time delivery, school capacity,
household inspector/history UI, multi-decade evidence and empirical fitness.
The equal goods/equity study pilots retain their version-7 profile and do not
silently become demographic experiments.

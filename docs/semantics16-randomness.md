# Semantics 16: independently keyed daily draws

Select `engine_semantics_version: 16` explicitly. The historical defaults and
Semantics 1–15 retain their stored behavior. No schema change is required.
The opt-in [price profile](../runs/price-lab-keyed.yaml) uses scripted providers
and both goods/equity study presets; the operator's existing fixed pilot profile
continues to use its declared Semantics 7.

Start Semantics 16 from fresh genesis. Upgrading an older checkpoint to this
contract is refused: historical causal origins and pending arrival keys cannot
be inferred safely. Ordinary forks retain their stored version; an existing
Semantics 16 checkpoint retains its recorded keys when forked.

## Draw contract

`mechanism_day_identity_v1` hashes canonical ASCII JSON containing the contract,
world seed, mechanism, day and typed identity components with SHA-256. The first
53 digest bits form an exactly representable integer seed; dividing by `2^53`
gives a uniform in `[0,1)`. Keys use neither Python's process hash nor a mutable
global cursor. Identical keys produce identical draws after reopening a run.

| Mechanism | Identity and interpretation |
|---|---|
| Demography | Person origin and hazard name; illness, recovery, mortality, birth and replacement delay remain separate |
| Arrival persona | Scheduled arrival origin; a fresh local persona PRNG per day/origin |
| Arrival bank | Separate arrival-origin PRNG; eligible bank set and regional preference remain endogenous |
| Arrival social contacts | One priority per arrival/resident origin; lowest three eligible priorities |
| Arrival tie strength | Separate draw per arrival/resident origin |
| Rumor audience | Immutable normalized shock definition, occurrence among identical definitions, and eligible person origin |
| Conversation pairing | One uniform per unordered pair of person origins; exponential priority `-log(1-u)/weight`, then existing coverage and disjointness rules |
| Scripted policy calls | World seed, day, purpose and person or outlet; conversations additionally bind partner, turn and retry |
| Memory compression | Separate daily and weekly purpose keys |

Conversation weights must be positive and finite to enter the new sampler.
Weights and eligible sets can change because of treatment; the common pair's
uniform stays fixed while its priority or selection can change. Ties in hash
priorities use origin keys. Query order does not choose the winning pair.

Genesis still uses its configured sequential engine/persona initialization.
Existing keyed compute-tier and city-home assignments use the recorded person
origin under Semantics 16. Engine/persona/lifecycle PRNG states remain stored for
historical compatibility, but the new daily sites do not advance those cursors.
Within a single scripted decision or persona generator, branching may consume
different numbers of its local draws; this contract isolates calls and
mechanisms, not every branch inside a policy. Live provider randomness is not
controlled by these seeds.

Semantics 16 request-cache identity includes the daily seed. Two requests with
identical rendered text but different outlet/person random keys therefore
retain separate recorded calls. This matters when newsroom staff die and both
outlets have a null desk-agent ID. Historical cache keys remain unchanged.

## Stable origins and boundaries

Genesis people retain `agent:<id>` identities. A birth key derives from the day
and parent's origin, consistent with the existing one-child-per-parent/day
contract. Replacement-arrival groups derive from the deceased's origin and day.
Other arrivals use schedule day, due day and occurrence among identical groups.
Unrelated event or shock insertions therefore do not change a common origin.
Repeated identical schedules are distinct occurrences, not inferred duplicates.

Keys are stored in existing birth, person-registration and arrival-scheduling
event payloads. Arrival age offsets use the origin key; an unrelated birth that
changes the arrival's database ID does not change its synthetic birthday basis.
Registration refuses to replace an existing origin. Lookup is uncached across
transactions so a rolled-back insertion cannot leave an identity attached to a
later reused database ID.

Engine-created staff without a causal origin retain a run-scoped numeric key;
the same numeric ID across diverged worlds does not establish a counterpart.
Firm/bank/outlet IDs remain their declared identities. Changing a shock's
definition creates a different event key. This version does not add a facility
for explicitly coupling different rumor definitions or dynamic staff origins.
Changed eligibility, scheduled dates, treatment-induced births/deaths, missing
counterparts, policy branches and resource constraints can change outcomes.

## Research use and acceptance

The strict study contract requires `seed_role:
initial_world_and_keyed_daily_streams` and `stream_contract:
mechanism_day_identity_v1` with Semantics 16. Older studies require their legacy
declaration. A mismatch fails before execution; frozen historical studies are
not relabeled. Both G2 and F2 drafts choose the contract from their explicit
configuration and retain equal goods/equity measurements.

Confirmatory execution remains unsupported. Common draws do not establish
causal design adequacy, power, empirical validity, a held-out hypothesis, or
independence among people in the same world. Genesis verification, accounting,
replay and source binding remain required before a pair is eligible.

Acceptance checks cover fixed vectors, mechanism/day/world-seed separation,
extra unrelated draws/events/births, reordered candidate rows, immutable shock
definitions, origin reassignment rejection, legacy Semantics 15 demographics,
and real G2/F2 source → pause → resume → recorded replay → read-only verification.
Results are recorded in the [execution log](plans/2026-09-06-research-city-execution.md).
Partial-phase study recovery remains a separate pending work package.

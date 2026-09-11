# Population control and external goods quotes

External observations previously omitted private firms: the query accepted
`operating` and `listed`, whereas the simulation uses `private` and `listed`
for active goods suppliers. The reproduced six-firm world exposed only its
one listed supplier. Quote rows also omitted their currency and region.

Draft Semantics 21 now includes private suppliers and adds `currency_code`,
`region_id` and `price_basis: posted_quote` to each goods row. The amount remains
the firm's posted `product_json.unit_price_cents`; observing a quote does not
record a sale or create an executed price. No ledger or schema change is needed.
Semantics 1–20 retain their previous observation and projection-hash contract.

Observation remains a `world.read` capability. A living adult outside the
modeled population retains observation access and its own account identities.
Its action catalog permits population-return commands only. Local production,
company authority and ownership continue to have separate checks. This extends
the [population boundary](2026-09-09-open-population-boundary.md) and follows the
[operator-capacity review](2026-09-09-population-recovery-authority.md).

## Executed workflow

[Eight focused cases](../../tests/test_population_control_workflow.py) cover
local/outside private quotes, currency/location/price meaning, four historical
versions and a complete seven-day World journey. An external actor arrives
through the real connection service, proposes departure, leaves on day 4,
observes prices while outside, requests return and returns on day 7. Source
and replay both reopen their Store during day 5 after MORNING. This declared
non-city runtime has 44 genesis identities and one external arrival; all 45
identities persist. It does not claim a native demographic horizon.

The two submitted turns retain exactly the same recorded observation envelopes
and projection hashes in replay. The original account IDs survive return;
outside days have zero model calls. Both ledgers reconcile, recorded replay is
exact and both closed databases pass source-validated hash-contract-v8 export.
Read-only verification preserves the source hash, modification time and absence
of sidecars. Every recorded provider is scripted and total provider cost is $0.

Receipts use `tmp/estate-finality-participation-control-quotes-*`. The original
three failures are retained under `reproduction`; the seven focused corrections
passed under `correction`. The full eight-case `workflow` passed in 77.71 seconds,
with 55,533,357 artifact bytes and 104,460,234,752 bytes free. Source files kept
their hashes and modification times throughout each run. The existing
Starlette/httpx deprecation warning remains.

The suite is included in the existing `research-population-commons` CI job for
Ubuntu/Windows and Python 3.11/3.12. Its exact 13-suite selection passed all
**169 tests in 437.20 seconds** locally on Windows/Python 3.11.15. The `ci`
receipt retained 856,155,339 artifact bytes and finished with 103,563,366,400
bytes free. All 1,163 counted sources kept their hashes and modification times;
staging stayed empty. This selection includes current population/Commons,
banking/finance, external gateway, golden replay and immutable Semantics-1/2
source checks. It does not establish full CI or the other configured platforms.

## Source review inventory

The audit at `C:/Users/matri/.codex/tmp/ae-302d0430` records 22 further original
candidate dispositions with exact current source coordinates and hashes:

| Scope | Reviewed distinction |
| --- | --- |
| Twelve external-service methods | Readable identity and owned accounts survive departure; local decisions, return commands, turn invalidation and replay have separate admission checks. The observation method contains this change. |
| Five manual-control methods | Current availability and uninterrupted lease history determine active control. An outside living adult receives a return-only lease. |
| Five business-control methods | Local operating authority is separate from shares; succession, guardian eligibility and dated stewardship preserve beneficial ownership and monetary boundaries. |

The consolidated original inventory now has **50 scopes matching reviewed
source and 100 remaining**. `ParticipantService.action_catalog` stays incomplete:
the outside early return, memory-free preview and context-derived firm options
are reviewed, but alternate catalog/service paths, including non-city lawyer
selection, still need explicit dispositions. Earlier unchanged source reviews
and their test receipts remain linked; they are not described as newly rerun.
The entire mixed scenario matrix and exhaustive caller coverage remain open.

Each seven-day source/replay database is 12,238,848 bytes. A read-only artifact
audit independently confirms six quoted firms in both submitted envelopes,
identical envelope hashes, the return-only outside catalog, 45 identities and
zero outside calls/provider cost. Two preliminary audit assumptions were
corrected against the database: the submission table's name and the non-city
genesis count. Those diagnostic helper versions are retained; neither changed
a scientific database or represents a failed World/replay test.

## Remaining acceptance

Continue the explicit business-control and manual/external admission inventory.
Review all action-catalog alternatives and their service entry points before
declaring that inventory complete. Source-scope review does not establish every
caller or the full mixed scenario matrix.

Schema 25 and public Semantics 1–20 remain supported; population migration 26 is
unregistered. The native horizon, full-prefix verification, full CI, W5 and
W6–W9 remain open, along with earlier provider/workflow/usability acceptance.
Goods and equity price discovery keep equal priority. Bounded local checks
retain the 40 GiB free-space floor; a new native run requires its separately
declared resource admission. No cleanup or paid-provider run is part of this
change.

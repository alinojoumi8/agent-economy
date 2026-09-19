# Historical household and public institution lenses

Status: implemented; verification is recorded in the
[execution log](2026-09-06-research-city-execution.md).
Scope: the next W4 city inspector slice, using existing W5 records. The full
[roadmap](2026-09-06-research-city-roadmap.md) remains active.

## Workflow

In City evidence, select a household or bank through the Keyboard explorer.
A visible person's inspector also links to their recorded household. Household
member buttons return to that person on the map, clearing filters that would
hide them. A bank-owned public place links to the public bank inspector.

The selection survives Atlas, 2.5D Diorama and recorded-day changes, reload,
browser history, and the existing city evidence bookmark. Selecting another
kind clears the previous selection and person follow. Camera and historical
scope remain independent. A selected identity with no visible record at a
different tick stays selected with an unavailable state; another person is
never substituted for it.

## Projection contract

The existing read-only `GET /api/v2/world-map` admits two opt-in layers:
`households` and `institutions`. The shared city loader requests them with the
existing map layers. Both sections carry their own tick, source, visibility,
availability and items inside the map's run/fork/tick/visibility envelope.
No additional live endpoint or provider request is needed.

- `households`: requires stored Semantics 15 or later. Its source is
  `recorded_household_membership` and visibility is `core_members_only`.
  Formation, dissolution, membership intervals, person entry/death and
  guardianship intervals are evaluated at the requested tick. Age derives
  from immutable birth ticks at 365 days per year, never today's mutable age
  or life stage. Child needs use only the exact selected day.
- The observer receives only core/pinned-core members. Both ends of a guardian
  link must be visible. Peripheral-only households, private child identities,
  account IDs/balances, purchase payloads, birth keys and exact residences are
  absent. The list is explicitly partial; it does not establish full household
  size. Newborns default to the peripheral tier, so they remain outside this
  ordinary observer lens unless already promoted by the model's existing rules.
  Current observer identity visibility applies to historical records; tier
  history is not reconstructed by this lens.
- Child needs preserve purchased/required units, recorded cents by currency,
  required care minutes and the stored care status. Missing records remain
  unavailable. Care requirements do not establish delivered care; child
  purchases do not establish a whole-household budget. Legacy dependent counts
  remain counts, not invented relatives. School age does not mean enrollment.
- `institutions`: source `public_bank_status`, visibility `public_status_only`.
  Banks are genesis identities. `bank:<positive ID>` identifies their name,
  currency and status, derived from the failure tick. It does not expose a
  balance sheet or imply that an open bank is liquid or solvent. Schools and
  public offices continue to use their supported place inspector.

The client rejects mismatched nested ticks, sources, visibility, malformed
records and duplicate identities before rendering a lens. URL selections
`household=<positive ID>` and `institution=bank:<positive ID>` are mutually
exclusive with person, firm, place and project selection. Unknown institution
kinds are not accepted. Existing deep links retain their behavior.

This slice adds no schema, engine semantics, monetary effects or writable API.
It does not reconstruct unsupported household wealth, retirement history,
partnerships, school enrollment, care delivery or estate settlement. Full W4
layout/usability acceptance remains pending; richer household and institution
fields depend on the existing W5–W8 mechanics roadmap.

## Verification

`tests/test_city_society_projection.py` covers historical births, departures,
death, custody, missing child needs, current-field poisoning, peripheral
redaction, source immutability, legacy availability, bank failure boundaries,
read-only HTTP and fork/tick rejection. Existing household and projection tests
remain the regression boundary.

`dashboard/tests/citySociety.test.js` covers validated selections, evidence
roundtrips, malformed/foreign frames and currency separation. The browser
cases in `live-city-context.spec.ts` cover the full selection/member workflow,
renderer switching, history/reload, unavailable selection, missing daily
records and keyboard/mobile interaction. The committed desktop and mobile
captures in `docs/research/assets/city-household-*.png` use a labelled synthetic
test world; they are UI evidence, not economic validation.

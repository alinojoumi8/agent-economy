# Local adjudication and continuing legal rights

Status: implemented and locally validated in draft Semantics 21. The original
population inventory has **119 reviewed scopes and 31 remaining**. Public
schema 25, maximum supported Semantics 20 and unregistered migration 26 remain
unchanged. Full mixed admission, CI, native acceptance and W6–W9 remain open.

## Corrected decision boundary

The direct legal decision service now validates its official's current residence
and residence on the requested day before recording authority or enforcing a
remedy. Missing or malformed residence evidence fails before effects. A stale
role cannot make an outside person eligible. The shared read-only assessment
also supplies the legal decision work queue.

Historical validation independently checks residence immediately before the
recorded authority event. A valid earlier decision survives a later departure
on the same day; returning later cannot legitimize a decision made while outside.
This uses existing immutable residence evidence and requires no schema change.

Four focused assertions failed on the original code: two malformed-history
entry points, stale-role admission, and an outside-decision historical audit.
The latter two deliberately inject faults. Ordinary departure already clears
personal roles, and the primary action executor already excludes outside actors.
These reproductions establish gaps in the direct service and its independent
audit; they do not imply that normal departure leaves an office active.

Six focused cases now cover those failures, once-only payment after restoring
the deliberately corrupted fixture, same-day event ordering, return without
office restoration, and actual enforcement against an outside respondent.
Invalid-history calls leave all table rows unchanged. An ineligible official
receives the existing recusal event without a decision or monetary effect.
Retry pays the original claim once; repeated decisions cannot pay it again.

The two new checks are gated to draft Semantics 21. Removing those two guards
produces an AST identical to the original legal-authority module. Existing
conflict rules, remedy calculations and the enclosing estate transaction remain.

## Reviewed rights and authority

Thirteen original candidate scopes were reviewed across legal institutions,
decision authority, representation, public estate administration, asset custody
and cash estates. Graph discovery and caller traces were checked against current
AST where index offsets were stale or draft symbols were absent.

- Party existence and financial ownership retain outside people's identities.
  Contract drafter authority is checked separately from offered party identity.
- A previously accepted resident lawyer can continue for an outside client's own
  rights. New acting authority stays local; unavailable lawyers and lost
  organization mandates end without rewriting past filings.
- Estate representatives use current local adults or guardians. If no private
  representative is available, an eligible regional official or a vacancy is
  recorded. Appointment never gives the administrator a beneficial interest.
- Pending cases and payment, indemnity or wage claims can keep an estate under
  administration after its physical or security assets have been disposed of.
- Beneficial paths and living cash heirs retain their economic rights while
  outside. Local activity filters must not confiscate title or cancel debts.

The source inventory is an inspection record, not proof of every historical
authority fault combination. Full mixed admission and current-version integration
remain necessary before enabling the draft.

## Validation

| Local selection | Passed | Pytest duration | Retained artifact bytes |
| --- | ---: | ---: | ---: |
| Seven legal, representation and estate suites | 133 | 388.77 seconds | 542,471,816 |
| Four population, civic, information/politics and recorded-replay suites | 27 | 122.15 seconds | 158,917,652 |

The six new cases are included in the 133-case selection. Documentation and the
unsupported-version admission check run separately. Every batch keeps source
hashes and modification times fixed and ends with an actual terminal result.
The existing Starlette/httpx deprecation warning remains.

Compatibility includes the existing three-day trustee recusal workflow, daily
restarts, a ten-cent award by another official, source export validation and exact
recorded replay. Closed source and replay are also inspected read-only. The
initial auxiliary audit refused its assumption of absent SQLite sidecars; the
source retains an empty WAL and a 32 KiB SHM from the older verifier. After proving
there were no WAL or journal frames, immutable inspection preserved the main
files and every retained sidecar's hash and modification time. Current
draft coverage repeats the nine-day professional-return/incorporation workflow
with exact replay and validated v8 exports. These are declared scripted fixtures,
not new autonomous native evidence or empirical fit.

The new suite is included in the existing lifecycle CI job, now 14 suites, with
its unchanged Ubuntu/Windows and Python 3.11/3.12 matrix. The entire expanded job
and full matrix were not rerun here; these checks ran on Windows/Python 3.11.
The replay batch ended with 336.5 GB free, above the
40 GiB reserve. No paid providers, cleanup or new native campaign were used.

## Next execution

Review the 31 remaining original scopes: political and regional authority,
initialization, observer/context surfaces and manual action entry points.
Complete the mixed scenario/admission matrix and current CI, while preserving
the original native source, frozen runtimes, interrupted verifier and recovered
copy under their unchanged cumulative allowances. Native horizon and full-prefix
verification remain incomplete. Close W5 against its full contract before W6–W9;
goods and equity price discovery retain equal priority.

Receipts: `tmp/estate-finality-population-adjudication-*`. The retained handoff links original/final sources,
failed probes, current scope hashes and closed-artifact checks. See the
[population contract](2026-09-09-open-population-boundary.md) and
[W5 acceptance audit](2026-09-09-w5-acceptance-audit.md).

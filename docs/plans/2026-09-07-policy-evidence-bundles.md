# Private evidence for policy comparisons

Status: private CLI implementation complete under W3/W4; broader regression and
committed-head CI verification are recorded in the execution log. This extends
the existing private evidence workflow to v3 policy studies from fresh and saved
worlds. Goods and equities remain equally primary. Operator model review,
launch and comparison integration remains a following step.

## Evidence contract

The policy reader distinguishes sealed final publications from current closed
pauses. A paused study must retain the original allowance, complete invocation
lineage, assigned model draws, closed worker/phase/input receipts and declared
measurement contract. It must have no final publication or sealed allowance.
Earlier progress is stale after another invocation. Unknown interrupted writes
are not cooperative checkpoints and cannot be transported as current progress.

The reader rechecks the prospective configuration and policy definitions using
their frozen prompt identity. It verifies every invocation's preflight, worker
order, reservation interval and scope; checks paused sources and completed
source/replay evidence; and recomputes the replicated estimator. Inherited
checkpoint costs remain separate from new execution and the shared allowance.
Missing executions and prices remain explicit exclusions.

`policy-working-verification-v1` reports a working publication with overall
eligibility `pending`. An individually completed world may retain eligible
evidence; that does not finalize the study. Changed scientific measurements or
summaries cannot enter a verified effect. Consistent diagnostic exclusions may
be retained with degraded verification. Reading does not resume a world, make a
provider call, require current credentials, or rewrite an original source.

## Archive contract

- `policy-study-evidence-bundle-v1` carries frozen or resumable final v3 results.
- `policy-working-evidence-bundle-v1` carries the latest closed v3 progress.
- Existing scripted final/working archive contracts retain their interpretation.
- An archive contract must match its independently loaded evidence contract.
  A policy archive cannot be relabelled as a legacy scripted archive.

Export holds both existing supervisor and worker owners while copying mutable
progress, including its unsealed allowance. Windows control bytes are read
through their owning handles. A busy or missing owner, changed budget/history,
stale progress, unsupported source or unfinished invocation refuses export.

Reuse the bounded path, alias, link, member-count, size and checksum guards of
the existing private transport. Every selected file is rechecked during copy;
the complete scientific proof and inventory are rechecked before exclusive
publication. Import extracts into a new directory and independently re-verifies
the copied evidence. Failed imports retain diagnostic files without a success
receipt. Neither operation replaces an existing destination.

The default bounds remain 2 GiB, 8,192 files, an 8 MiB index and portable member
names of at most 240 characters. Short import paths remain appropriate on
Windows. Runtime and original source checkout are not included. These private
archives may contain recorded communications, local paths and source history;
they are not dashboard projections. Local checksums prove consistency, not the
authenticity of an unknown publisher or the accuracy of provider invoices.

## Readability and execution authority

Relocation changes the caller's evidence roots, not the bytes of the original
manifest or budget. A copied unsealed allowance is scientific evidence; import
does not grant another running budget or adopt the copy into the operator.
Runtime resume continues to require the original namespace, code, configuration,
inputs and allowance. Original studies can later resume without changing an
already exported pending archive. The [policy operator interface](2026-09-07-policy-operator-workflow.md)
now reads these archives using distinct v3 comparison/progress contracts.
Configured policy launches retain their original job and allowance; import does
not adopt a copied archive into that authority.

## CLI workflow

```powershell
.\.venv\Scripts\python.exe -m research.policy_results <results-or-current-progress.json> --data-root <data-root> --out-dir <report-root>
.\.venv\Scripts\python.exe -m research.study_bundle export <results-or-current-progress.json> <private-evidence.zip> --data-root <data-root> --out-dir <report-root> --expected-sha256 <reviewed-result-hash>
.\.venv\Scripts\python.exe -m research.study_bundle import <private-evidence.zip> <new-private-directory> --expected-sha256 <reviewed-archive-hash>
```

A successful read or import of working evidence remains pending. Verify an
imported result using the returned result path and the new directory's `data`
and `reports` roots. Import neither installs bundled code nor enables execution.

## Acceptance and verification

1. Exercise actual loopback HTTP policies from fresh/saved worlds with frozen,
   day and phase execution. Export/import both current pending and final evidence.
2. Include multiple invocations and a completed cell before a paused cell. Bind
   original budget usage, source history and both price domains after relocation.
3. Refuse busy owners, missing or changed allowances, unfinished invocations,
   stale progress, altered phase/source/transition evidence and archive relabelling.
4. Recompute measurements despite resealed reports; forged values cannot create
   a verified effect. Preserve exclusions and the pending/final distinction.
5. Prove provider-free, read-only historical loading, immutable original sources,
   and rejection of imported-budget execution. Retain malformed-archive guards.
6. Run the scripted bundle/recovery, v3 policy and legacy replay regressions,
   documentation checks and required/full CI at the committed revision. Use
   fresh short pytest roots and the 40 GiB free-space floor.

The first complete focused suite passed **32 tests** on Windows/Python 3.11.15
in 375.25 seconds. It includes all six execution paths, resealed false prices and
provider totals, imported-execution refusal, CLI transport and malformed input.
All 352 Python sources compiled in memory and `pip check` passed. The dedicated
CI job has a 15-minute bound; required/full CI and compatibility results belong
in the [execution log](2026-09-06-research-city-execution.md) and draft PR #82.
The compatibility selection passed **237 tests** (986.95 s). Review then found
and fixed malformed catalog metadata interrupting valid study discovery; the
library, legacy working-evidence and documentation follow-up passed **37 tests**
(34.97 s), including four malformed-metadata cases. The existing Starlette
TestClient deprecation warning remains.

Controlled fixtures establish evidence transport, not live-provider readiness
or economic realism. No paid-provider rehearsal, cleanup or merge is part of
this implementation step. The broader five-part roadmap remains active.

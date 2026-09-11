# Native horizon outcome — final verification pending

The restored scripted Semantics-20, seed-1 campaign closed day 14,600. The native
execution is complete; recovered recorded replay is running. Full-campaign
exact comparison, export and independent readback have not started. This note
records the terminal supervisor counters, not a
completed W5 admission or an empirical claim about a real economy.

## Recorded outcomes

| Measure | Day 12,864 | Day 14,600 |
| --- | ---: | ---: |
| Population in the closing census | 17 | 16 |
| Active households | 9 | 9 |
| Total people recorded with birth origin | 7 | 7 |
| Total recorded deaths | 15 | 16 |
| Living adults born during this run | 6 | 5 |
| Employment records for people born during this run | 0 | 0 |
| Recorded goods-sale events | 6,318 | 6,318 |
| Recorded equity trades | 265 | 265 |

The terminal record also reports 16 estate cases, 19 retirement events and
267,837 recorded calls at zero provider cost. Native execution plus its recovery
consumed 27,631.405 seconds within the original 28,800-second allowance. All 40
annual household reports are present in the final verifier's report lineage.

The two endpoints have identical cumulative sale/trade counts over 1,736 days.
This indicates no additional recorded executions in that interval under the
append-only history contract. It does not establish that quotes or valuations
were unchanged, and it is not a substitute for the pending complete replay audit.

## Recorded employment opportunity

A bounded read-only diagnostic of the closed source found three firms, all
founded at genesis, with bankruptcy ticks 90, 150 and 2,101. Only two job postings
are recorded, at ticks 19 and 382. The last employment began at tick 386, and the
last recorded employment ended at tick 2,101. No later firm entry is recorded.

The first person born during the run reached adulthood at tick 7,563, which is
5,462 days after the last recorded firm bankruptcy. No birth-origin person has
an employment record or a recorded job posting during their adult lifetime.
Their recorded time allocations contain received care, but no delivered
employment work. Thus this campaign offers no observed later employment demand
against which to assess the younger cohort's job readiness.

This is a diagnosis of the recorded opportunity set, not a causal estimate or
proof that firms could never re-enter. Historical vacancy availability cannot
be reconstructed from the final job status alone. The source database and its
existing sidecars were hash-checked before and after the diagnostic and remained
unchanged. See `native-work-opportunity-diagnostic.json` for the exact SQL,
person-level dates and firm records; the inspection took 9.016 seconds.

The stored run configuration has no `entrepreneurship` section. In the frozen
`agents/prompts.py`, `_entrepreneurship_opportunity` defaults its `enabled` flag
to false and returns no opportunity in that case. The scripted citizen policy
can consume a supplied founding action, and the engine has a company-founding
handler. Therefore this experiment did not activate the native entrepreneurship
path; its absent firm entry is not evidence that this existing feature failed.
The separate `firms.recruit_to_target=true` setting did not enable firm entry.

`native-entrepreneurship-config-diagnostic.json` binds this finding to the source
database and frozen code hashes. It also records the one living lawyer as retired
at the final tick. That is a further service-capacity condition to inspect before
a prospective incorporation experiment, not proof that every legal action would
be rejected. The completed run's settings and outcomes remain unchanged.

A read-only final-tick screen also found that all five living birth-origin
adults have zero checking cash and risk tolerance 0.5. Under the existing
default founding screen (minimum risk tolerance 0.65, 100,000 cents opening
capital, 100,000 cents personal reserve and a 2,500-cent permit fee), none passes
the basic numeric requirements. They are healthy, unretired and aged 25–37.
Enabling the entry flag only at this final state therefore would not supply
these people a default founding opportunity. This screen does not assess every
other person or prove the absence of every possible financing path.

The existing `autonomous_preseed` option does not remove that initial personal
capital requirement. In the frozen `agents/prompts.py`, lines 1923–1947, it
supplies a `pitch_vc` action for an already existing firm with a business idea,
after its founding delay, provided it has no prior pitch. The action requires
that firm's ID. The inspected file still hashes to
`ef04cafed1c26ec698a04cf3b4a92523e593b6adaa3a81cb44976fd240659bd1`.
The current worktree retains this ordering at lines 1986–2010. This is a
code-path finding, not an executed financing experiment: enabling the option
does not itself finance a cashless person's incorporation. A future experiment
must distinguish capital to incorporate from financing after incorporation;
neither an offered pitch nor an incorporation proves funding, hiring or output.

## Implications for the planned work

The model has reached adulthood, death and estate transitions, but this campaign
does not demonstrate employment for a person born during the run. Preserve this
outcome. Adulthood does not guarantee a job, and a lack of employment alone does
not make the recorded accounts incorrect or authorize changing the run.

For W6, keep education outcomes distinct from job availability and show whether
firms actually demand the resulting skills. For W7, evaluate whether productive
firms survive or enter and whether households can transact with them. For W8,
test whether financing supports those activities without creating unrecorded
money or guaranteed profitable firms. These follow the existing work-package
order; this note does not begin their implementation before W5 admission.

Do not treat the productive-generation acceptance requirement as satisfied by
this campaign, or simply repeat the same recruitment setting expecting a
different opportunity set. A further prospective experiment needs to distinguish
firm survival/entry and vacancies from applicant behavior. Any controlled demand
benchmark must declare its intervention and remain separate from evidence of
unassisted firm entry; it must not alter this completed source or guarantee a hire.

The next opportunity experiment should explicitly activate and report the existing
entrepreneurship capability, its eligibility/capital thresholds and legal-service
requirements before evaluating entry or hiring. It must distinguish that policy
intervention from changes to production, education or financing, retain the current
run as its original protocol's evidence, and report refusal or non-entry honestly.
It also needs to separate employer entry from a birth-origin person's own ability
to finance a startup. Do not infer that turning on the entry flag is sufficient,
or lower thresholds/endow actors after seeing these outcomes to manufacture a
productive-generation result. Specify any policy treatment prospectively and
retain the full economic and eligibility evidence in both markets.

For W9, report market inactivity explicitly in both goods and equities. A carried
last-trade price is not a newly discovered price. Research comparisons should
show execution coverage, the age of the last execution and missing observations,
alongside the accounting and replay results. This campaign must not be described
as evidence of sustained price discovery over the full 40-year horizon.

## Evidence

All paths below are relative to
`data/recovery/environment-cleanup-69dbcab9/`:

- `native-continuation/segment-005/receipt.json`: accepted day 12,864 counters.
- `native-continuation/receipt.json`: terminal day 14,600 counters and time/closure proof.
- `original-controller.py`, lines 115–125: the exact counter queries, including
  the living-adult and birth-origin employment definitions.
- `campaign-verifier-campaign-v2/report-lineage.json`: all 40 original/recovery reports.
- `campaign-verifier-campaign-v2/owner.json`: interrupted original verification
  ownership; this process is absent and its artifacts remain retained.
- `campaign-replay-continuation-v1/owner.json`: current replay continuation
  ownership, to be checked against the process before relying on liveness.
- `campaign-replay-continuation-v1/plan.json`: remaining replay allowance and
  preservation checks; full campaign verification is still pending.
- `recovered-analysis-smoke-closure.json`: the small recovery rehearsal's exact
  comparison, export/readback and life-course checks; not full-campaign proof.
- `native-work-opportunity-diagnostic.json`: read-only cohort, posting,
  employment and firm chronology, with source/sidecar preservation checks.
- `native-entrepreneurship-config-diagnostic.json`: stored entrepreneurship
  configuration and frozen policy/handler identity; the entry policy was disabled.
- `native-entrepreneurship-basic-screen.json`: final-tick cash/risk/age inputs
  compared with the existing default founding thresholds; no experiment was run.

See [environment recovery](2026-09-11-environment-recovery.md) for the preserved
cleanup failures, source reconstruction limits and remaining release gates.
# Verification update — replay timeout

On September 11 at 16:54 UTC, continuation session `61765` was independently
closed as failed after exhausting the replay allowance. Its last reported
checkpoint was day 13,000 of 14,600; this is not an exact final database tick.
The native simulation remains complete and its source hash is unchanged.
Full replay comparison, export and readback remain unexecuted. References below
to the continuation as current describe its earlier running state and are
superseded by this terminal update. See the environment recovery log and
`campaign-replay-allowance-terminal-audit.json` for the evidence. No retry was
started and no W5 acceptance was granted.

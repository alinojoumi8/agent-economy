# Long-horizon verification and population repair

Baseline: `f10d60f95dc99f7dde11c14a6e66e8ed520e3c04`; original failed run:
`9bf47708aebcf19a7df5ceec39f196eed2f13123`. The user authorized fixing both
new blockers before the one corrected 1,000-tick experiment.

Capability checks defined before implementation:

- Complete canonical source/replay verification within the unchanged 600-second,
  8-GiB scratch, 64-MiB record, bounded-cache limits. Profile a small immutable
  prefix first; optimize the measured serialization bottleneck without changing
  canonical bytes, ordering, multiplicity, or valid/invalid reference behavior.
- Preserve oversized-record, expanded-reference, timeout, scratch-space, cleanup,
  Unicode/nonfinite-number, duplicate and missing-reference rejection checks.
- Validate a stable-lifecycle population by independently reconciling the initial
  cohort, retained deaths, scheduled arrivals, actual arrivals, living counts and
  regional movements. Do not silently replace expected population with observed
  totals. Reject missing/duplicate/tampered lifecycle evidence and unexplained
  additions/removals. Keep legacy fixed-population receipt behavior identifiable.
- Preserve the simulation's economic and lifecycle policy. Explicitly version and
  record any acceptance-contract change; do not claim old and new acceptance
  contracts are identical or relabel the original failure as a pass.
- Persist a useful failure receipt if verification cannot complete, including
  available runtime measurements, source before/after hashes and the exception;
  never invent an exact replay proof or lose all evidence to an exception.

Regression checks: bounded and historical golden replay, source immutability,
scale validation/economic-health/profile suites, lifecycle/arrival provenance,
required repository checks, CI and CodeRabbit against the actual PR base.

Acceptance: preserve the original failed evidence; prove the revised verifier on
retained artifacts as a separately labelled read-only diagnostic, then freeze the
validated exact commit and launch exactly one fresh corrected 1,000-tick run.
Keep seed 42, initial 308 agents, checkpoint interval 100, retention two and the
2,048-MiB RSS limit. No live providers, Hermes, observatory, merge or deletion.

Retained engine evidence (2026-10-18): the v3 population reader was also checked
against the original 1,000-tick source `60f83f125d`, not only hand-built fixtures.
It reconciled six real deaths, six scheduled arrivals, all tier changes and 308
living agents across 314 retained rows. The source SHA-256 is
`8ca52adfb56adc633cf9c7b66572aa341c89d92304fdc5ffad4293277332d3b5`;
the ignored `reports/out/blocker-repair/population-reconciliation-final.json`
records the result and unchanged simulation policy. Semantics 7 stable lifecycle
emits a NIGHT_CLOSE death followed by its subjectless replacement schedule
(`Lifecycle._settle_death`/`schedule_arrival`); `World._spawn_due_arrivals` records
the schedule event ID, and `RegionalEconomy._rebalance_tiers` uses the same phase.
Keep these version-specific checks strict. This diagnostic is not a retroactive
pass for the original v2 experiment or a substitute for the corrected run.

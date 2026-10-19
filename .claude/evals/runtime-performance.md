# Runtime performance repair

The 308-agent, provider-free scale experiment spends substantial CPU time per
tick despite low memory use. The user stopped its first corrected launch and
authorized measured performance repairs before a fresh long-horizon experiment.

## Capability checks

- Profile copied early and late retained worlds; retain CPU, SQL, phase, memory,
  and wall-clock measurements with source/commit identity. Never mutate the
  original experiment or reuse its launch claim.
- Reduce the measured dominant work on identical input snapshots. Compare
  unprofiled baseline and repaired timings, reporting both individual cases and
  instrumentation limitations rather than inventing a speedup from profiler data.
- Exercise external-agent observation and action admission while the world runs;
  measure API latency/event-loop responsiveness separately from tick throughput.
  Retain authentication, ordering, admission, and transaction boundaries.

## Regression checks

- Preserve canonical table contents, row ordering/ties, seeded randomness,
  historical v1/v2 replay, receipt fields, and source immutability.
- Keep the same simulation/economic/lifecycle policies, 308-agent profile,
  seed 42, checkpoint interval 100/retention two, 2048 MiB memory cap,
  and 600-second final verifier limit.
- Test valid and rejected inputs, deterministic resume/replay, and resource
  behavior of each changed path. Keep original failures and interrupted evidence.
- Run repository checks and current-commit CI, then complete CodeRabbit review
  against the actual PR base, addressing only findings within this scope.

## Long-run gate

Only a validated, frozen commit may consume the one new optimized experiment.
Retain its own guarded launch claim, PID/creation time/command/cwd, receipts,
logs and artifacts. Never silently restart a failed experiment. Report exact
replay, memory/runtime, checkpoints, database growth, and economic acceptance
before observatory work. No live providers or Hermes are part of this test.

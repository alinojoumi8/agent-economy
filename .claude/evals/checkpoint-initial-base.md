# Large initial-base checkpoints and certifi repair

- Upgrade only certifi to a nonvulnerable release and regenerate the universal,
  hashed lock without changing unrelated package versions. Audit must pass.
- A fresh immutable base for the retained 5.57 GB private copied SQLite image
  must complete in under 5 seconds, with all capture, native SQLite proofs,
  compression, disk writes, fsync, full pack and decoded-chunk verification,
  publication, retention and process shutdown included.
- Aggregate parent/descendant sampled RSS must stay below 2048 MiB; sampling
  errors fail closed. Preserve raw-reader SIGBUS isolation and writer exclusion.
- Restore must match exact input bytes and all state/ledger/schema evidence.
  Invalid bytes, failed durability or insufficient disk space must prevent root
  publication. Earlier failed experiments remain retained.
- Validate unchanged-base and real 900-to-1000 delta behavior, historical restore,
  concurrent native WAL-index polling, retention, quarantine and bounded queues.
- Freeze reviewed source before full gates, current-base CodeRabbit and exact
  commit CI. Then claim and run one fresh full 1000-tick source/exact replay and
  economic acceptance test with original limits, policy and seed. Preserve all
  results and report every failure before observatory.

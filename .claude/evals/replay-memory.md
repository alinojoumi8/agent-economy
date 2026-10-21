# Replay memory repair

Baseline: `9bf47708aebcf19a7df5ceec39f196eed2f13123`.

Capability checks defined before implementation:

- Retained replay-call payloads and final attestation must not allocate memory
  proportional to the complete prompt/response history. Exercise large distinct
  payloads and measure Python allocations and process memory separately.
- Preserve every attestation field, sorted canonical digest, duplicate record,
  purpose count, missing/unexpected identifier, and Oracle-only digest.
- A failed replay admission must remove only its consumed calls, restore the
  original counters, and allow the same recorded call to be retried.
- Temporary evidence must remain private and be cleaned on gateway close,
  including repeated close and exceptional paths. Never write to source runs.
- The 50 ms memory sampler must retain only aggregate statistics per stage,
  producing the same counts, extrema, rounding, and receipt fields.

Regression checks: source lifecycle and legacy golden replay, bounded replay
verification, information replay rollback, Oracle and arrival call accounting,
scale-validation receipts, and the required repository/CI gates.

The original running checkout and databases remain untouched. The corrected
formal run must wait for the original terminal outcome and a frozen verified
repair commit. Keep the same 1,000-tick profile and all acceptance limits.

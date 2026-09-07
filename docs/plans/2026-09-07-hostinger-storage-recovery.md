# Hostinger storage and recovery implementation

Authorized September 7, 2026. Branch `codex/hostinger-storage-recovery` starts
from `origin/main` at `fe43aa4`; the research-city worktree remains independent.

## Decisions

- Deploy the application on a Hostinger VPS using Docker Compose. Amazon is
  not required. Stream SQLite changes with pinned Litestream 0.5.17 to a
  separately provisioned SFTP server with SSH host-key verification.
- Keep agent memories, accepted actions, ledger records and exact model outputs
  together in each database. Compress model payloads losslessly inside SQLite
  so a backup cannot become separated from an external memory/blob store.
- Preserve the legacy plain representation and logical replay/hash contracts.
  Enable the new storage representation through operational policy. Provide a
  plain SQLite export for tools that do not understand the representation.
- Keep four verified recovery checkpoints by default in the Hostinger policy.
  Pins protect research milestones; count/byte limits never override pins or
  the minimum valid recovery set. Keep checkpoint bodies outside the directory
  Litestream watches.
- Bound full hosted snapshots as well as local checkpoints. In streaming mode,
  periodic full hosted copies are disabled; explicit pause/stop snapshots remain
  available. Recovery from a missing run cache uses the stream and fails visibly
  if the stream cannot be restored, rather than silently loading a stale copy.
- Add disk admission/reserve checks and run/tenant byte budgets. Apply policy on
  resume without rewriting the scientific run configuration.
- Retain complete originals in compressed, verified run archives. Memory
  summaries are retrieval aids and never authorization to delete experiences.
- Include PostgreSQL catalog backup and restore instructions. The site server
  and its local backup volume are one failure domain; an off-server destination
  must be provisioned before deployment.

## Work and validation

1. Lossless payload codec; legacy readers, canonical hashes and exact replay.
2. Verified checkpoint rotation, pins, storage policy and disk budgets.
3. Hosted snapshot rotation and Litestream restore integration.
4. Hostinger Compose, pinned binaries, SFTP setup and catalog backup tooling.
5. Disposable restore drills with the real Litestream binary, failure tests,
   repository smoke/compatibility tests, documentation and a reviewable commit.

Only disposable test data may be pruned during validation. This implementation
does not clean existing research checkpoints or deploy to a real VPS. Merge to
`main` is intentionally deferred for user review.

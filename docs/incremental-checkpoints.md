# Versioned incremental checkpoints

This opt-in storage format changes checkpoint storage, not simulation or economic
semantics. Historical standalone SQLite checkpoints and v1 manifests remain the
default and retain their original verification and restore behavior.

```yaml
checkpoint_format: incremental-v2
checkpoint_every: 100
checkpoint_keep_last: 2
checkpoint_dir: data/checkpoints
```

Each `RUN_tTICK.icp.json` descriptor points to a SHA256-bound immutable root in
the adjacent `.checkpoint-v2` directory. The first root indexes an immutable
base. Subsequent roots contain changes relative to that base, with complete
coverage reconstructed in bounded space; delta chains do not grow with time.
Page-aligned 64 KiB chunks have BLAKE3 hashes. Changed chunks use bounded lossless LZ4 blocks (or raw bytes for incompressible
input). New blocks are appended to a private pack, flushed, read back and verified, then published immutably. Unchanged chunks
are independently read and verified on each save. Root and descriptor publication
comes last. No arbitrary file paths are accepted from manifests.

Pack headers include an independent storage nonce, which consumes no simulation
randomness. This allows a fresh recovery base to preserve an existing corrupt
object instead of overwriting it. World checkpointing logs a rejected base and
attempts one fresh base; source-integrity failures are never retried this way.
The low-level save API stays strict unless base recovery is explicitly enabled.
Rejected descriptors and corrupt objects remain evidence. They can stop
collection and require operator attention even after a new recovery point works.

Packs below half live utilization are compacted within the save operation.
Compacted blocks receive full stored-byte verification. Immutable base packs and
pinned roots remain protected; live cold appends cannot indefinitely pin large
obsolete hot rewrites. Metadata caches are bounded and last only for one archive
lock operation; each save independently verifies its stored bytes.

Capture excludes SQLite writers while reading a logical image of the main file
and its committed WAL frames. Native SQLite integrity, schema, state, PRNG and
ledger checks run at that same cut. The complete save timer includes all checks,
durability and requested retention. A small bounded thread pool overlaps native
checks, hashing and verification; world ticks remain sequential. This does not
add simulation multiprocessing. Long saves remain off the async serving loop,
although other SQLite writers must wait for the capture boundary.
Hashing and compression use two workers with at most three ordered 1 MiB input
batches. The source file handles have one reader; no full-image work queue exists.
SQLite integrity and ledger checks have separate native readers at the same
writer-excluded cut. Common state/core SHA256 fields keep v1 canonical semantics;
the storage root digest is not relabelled as a raw SQLite database SHA256.

Keep descriptors **and the entire referenced archive together** when moving a
world. A descriptor alone is not a standalone SQLite database. The regular fork
command accepts both formats:

```bash
python run.py --fork /absolute/path/RUN_t100.icp.json
```

To materialize an unchanged standalone image into a fresh path:

```bash
python -m engine.incremental_checkpoint /absolute/path/RUN_t100.icp.json /absolute/path/restored.db
```

Restore verifies chunk lengths/hashes, native SQLite integrity and independently
recomputed evidence before publishing. It refuses to overwrite an existing file.
Research admission and the operator checkpoint catalog can materialize private
copies for existing legacy readers. Admission still checks its original size,
state, random-stream and influence constraints; storage format does not confer
research acceptance. Copying a large image and restoring it have their own cost.

Pins protect descriptors and their dependencies. Retention validates current
roots, preserves pins and other runs in the same directory, and only then
collects unreferenced packs/roots. Invalid metadata or corrupted referenced bytes
stop collection. Capture, restore, pinning and collection share an archive lock.
An interrupted save may leave an unreferenced immutable object; it cannot replace
a valid published checkpoint. Storage-policy free-space limits still apply. As with legacy rotation, the byte
budget is a retention target: pinned points and the minimum two recovery points
are protected, with excess bytes reported rather than blocking every future save.
Shared archives count their physical packs once against the archive target. The
v2 logical image is bounded to 16 GiB and metadata to 64 MiB. Larger historical
v1 images are unaffected. Scratch copies default beside the archive on disk,
with an explicit reader scratch override; they never default to RAM-backed `/tmp`.

## Measurement boundary

The five-second save target and 2048 MiB RSS limit are unchanged. Initial base
creation is a full write and is measured separately, not hidden outside the save
timer. Prototype copied-data measurements found a 19.87-second base and
4.33–4.56-second unchanged/localized saves, with 39.21 MiB RSS and a 24.69-second
restore. Those are **prototype diagnostics**, before final integration and new
pack readback; they do not certify current-code p95, realistic 100-tick growth,
cold-cache behavior, production concurrency or another 1,000-tick acceptance run.
Current validation receipts must retain any remaining latency failures.

The first full-size tick-900→1000 trial at commit `0c71927` failed: 53.82s
for a 3.40 GiB rewrite, and 8.10–12.40s for unchanged/retention saves. Its
1 MiB uncompressed format was a prototype, not a released v2 contract. Finer
64 KiB LZ4 blocks are under validation; no current target pass is claimed.

The next compressed prototype (`87a9974`) measured 8.15s for the real interval,
6.00s unchanged and 8.81s with retention; these still failed five seconds. Its
15.00s base and 25.87s restore were separately measured, with 231.20 MiB RSS and
exact restored bytes. Later buffering, bounded parallel batches, compaction and
operation-local metadata reuse require their own retained measurements.

The maintained `runs/diagnostics/incremental-checkpoint-canary.yaml` uses the
existing scripted scale rehearsal's population/communications contract for a
bounded storage regression. The earlier six-citizen fixture completed exact
20-tick replay but failed the runner's fixed population/communications guards;
that failed receipt is retained rather than changing the guards.

A separately authorized full validation can use
`runs/acceptance/scale-270-recovery-buffer-lifecycle-incremental-1000.yaml`.
It changes only checkpoint storage selection from the existing v3 lifecycle
profile. Seed, simulation policy, interval, retention and acceptance limits stay
unchanged. Preparing that profile does not launch or certify a full experiment.

The format requires a local filesystem with hard links and atomic rename.
Whole immutable-pack digests cover headers and dead packed bytes in addition to
per-chunk logical hashes. Large verification plans use two bounded native workers;
no full-history future queue or verification cache survives an operation.

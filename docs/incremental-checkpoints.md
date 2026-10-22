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
Raw database, WAL and WAL-index file descriptors belong to a separate spawned
reader with no SQLite connections. The parent retains SQLite's writer-exclusion
transaction until that reader has verified the final WAL boundary and exited.
Closing raw descriptors in the SQLite process cancels its POSIX advisory locks;
another process can then invalidate a still-mapped WAL index and cause SIGBUS.
The isolated reader prevents this lock loss, including when capture fails.
Direct image reads cross the boundary in at most 8 MiB batches; reader startup,
shutdown and verification remain inside the save timer and memory accounting.
Hashing and compression of large owned images use at most four spawned read-only
readers and five ordered 8 MiB ranges. Only new encoded blocks and metadata
cross process boundaries; no full-image work queue exists. Each reader binds
main/WAL file identities to the parent's writer-excluded cut, holds no SQLite
connection, and closes its handles when the operation ends. Small images use
two native threads and three 1 MiB batches. The four verification workers are
reused for existing and newly stored objects within a save, then joined.
Large fresh bases use at most eight spawned SQLite-free workers and nine
ordered jobs. Each job reads at most 128 MiB of logical pages through the same
committed cut, writes one immutable pack with an at most 8 MiB buffer, fsyncs it,
hashes every stored byte and verifies every decoded chunk. Only metadata crosses
process boundaries. All jobs finish and workers exit before root publication.
The free-space reserve is checked before each bounded write; write, fsync or
readback failures prevent publication. Existing-base saves batch writes in at
most 8 MiB buffers, checking the free-space floor before each batch. Their full
disk readback overlaps the native source scan and existing-root decoding.
No validation or durability work is moved
outside the save timer.
SQLite integrity and ledger checks have separate native readers at the same
writer-excluded cut. Common state/core SHA256 fields keep v1 canonical semantics;
the storage root digest is not relabelled as a raw SQLite database SHA256.

For large main databases, a disposable spawned SQLite-only reader performs the
complete native `quick_check`, using at most 1 GiB of mapped input and a 2 MiB
reader cache. Pages beyond that prefix still use ordinary SQLite reads. Small
unmapped readers use a 64 MiB cache. Raw source-capture workers remain SQLite-free.
SQLite documents that mapped I/O faults can terminate a process; isolating this
reader turns a native reader failure into a rejected checkpoint rather than
terminating the live SQLite owner. Unsupported mapping falls back to normal
SQLite reads. All reader processes finish before publication; aggregate memory
sampling includes them. See [SQLite mapped I/O](https://sqlite.org/mmap.html).

Requested retention reuses decoded metadata for the newly created root only
after reading back and comparing every stored root byte before descriptor
publication. These proofs are bounded to the same archive lock and save; no
persistent or stat-only integrity cache is used. Corrupt readback preserves the
older recovery point and prevents the new descriptor from being published.

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
stop collection. Capture, explicit restore, pinning and collection share an archive lock.
An interrupted save may leave an unreferenced immutable object; it cannot replace
a valid published checkpoint. Storage-policy free-space limits still apply. As with legacy rotation, the byte
budget is a retention target: pinned points and the minimum two recovery points
are protected, with excess bytes reported rather than blocking every future save.
Shared archives count their physical packs once against the archive target. The
v2 logical image is bounded to 16 GiB and metadata to 64 MiB. Larger historical
v1 images are unaffected. Scientific reader scratch uses `scratch_dir` or the system temporary directory;
configure a private disk-backed `TMPDIR` when materializing large images.

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
per-chunk logical hashes. Large verification plans use four spawned read-only processes, avoiding
contention with capture while retaining full pack and decoded-chunk checks.
Workers receive bounded metadata, read immutable archive bytes, and are joined
before the save finishes. Spawn avoids forking SQLite connections or threads.
Memory receipts count aggregate parent-plus-descendant RSS. This parallelizes
checkpoint verification only; world ticks remain sequential. There is
no full-history future queue, and no verification cache survives an operation.

World saves register the durable new point using a worker-owned SQLite connection
before any rotation. A catalog-write failure preserves previous recovery points.
The low-level API leaves source rows untouched unless catalog registration is
explicitly requested. Descriptors must use `.icp.json` and cannot replace their
source database. Rejected evidence prevents collection until operator review;
a fresh recovery point does not relabel or erase the older failure.

At `061cd71`, spawned verification improved unchanged API saves to4.48–4.56s,
but actual interval8.33s and complete World saves4.54–5.33s still failed the
unchanged target. Aggregate sampled process-tree RSS was369.98MiB; restore bytes
and private input anchors matched. Follow-up read-only range and worker-reuse
changes require fresh complete measurements; private5.36s phase diagnostics
are not acceptance proof. All earlier failures remain retained.

Scientific readers materialize into private external scratch (`scratch_dir` or
`TMPDIR`), never beside the descriptor. They open no writer lock in the source
archive. All immutable pack, decoded-chunk and SQLite proofs remain mandatory;
concurrent pruning can reject a reader, but cannot publish an unverified copy.
Select a disk-backed private `TMPDIR` with enough space for large restores.
The explicit restore command retains its archive-lock behavior.

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

Capture excludes SQLite writers while reading a logical image of the main file
and its committed WAL frames. Native SQLite integrity, schema, state, PRNG and
ledger checks run at that same cut. The complete save timer includes all checks,
durability and requested retention. A small bounded thread pool overlaps native
checks, hashing and verification; world ticks remain sequential. This does not
add simulation multiprocessing. Long saves remain off the async serving loop,
although other SQLite writers must wait for the capture boundary.

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

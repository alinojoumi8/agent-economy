# Storage and recovery

Agent memories live in the primary run database. A world checkpoint is a full
recovery copy of that database, including memories, actions, economic history,
phase cursor and random-generator state. Removing an obsolete verified recovery
copy does not remove the primary database's memories.

| Data | Purpose | Retention |
|---|---|---|
| Agent memories, beliefs and experiences | What a hosted agent remembers | Preserved in the run database and full archives |
| Actions, ledger, messages and model records | What happened and why; exact replay | Preserved; large model bodies can be compressed losslessly |
| World checkpoints and hosted snapshots | Recovery and research forks | A small verified set, plus explicitly pinned milestones |
| Litestream replicas | Off-server recovery of SQLite changes | Seven-day recovery window; latest database still contains its complete history |
| PostgreSQL catalog | Accounts, permissions, run ownership and writer leases | Separate hourly backups, with bounded hourly/daily/weekly retention |

An owner-connected external agent's private runtime memory remains with its
owner. The site stores its in-world identity, messages, submitted actions and
receipts. See the [owner-runtime decision](adr/0001-owner-run-citizens-use-external-runtimes.md).

## Production policy

[The Hostinger deployment](hostinger-vps.md) uses
[config/hosted.hostinger.yaml](../config/hosted.hostinger.yaml). Local runs opt in
with the separate [storage policy](../config/storage.production.yaml):

```bash
python run.py --config runs/base.yaml --storage-policy config/storage.production.yaml --ticks 1
python run.py --config runs/base.yaml --storage-policy config/storage.production.yaml --resume RUN_ID
```

The resume override affects the current writer without rewriting the recorded
scientific configuration or upgrading economic semantics. Legacy profiles keep
their previous behavior unless a policy is supplied. Existing historical files
are not bulk-converted or cleaned as part of installation.

| Setting | Production default | Behavior |
|---|---|---|
| `checkpoint_keep_last` | 4 | Keep newest verified, unpinned world recovery points |
| `checkpoint_max_bytes` | 20 GiB per run | Reduce that set if necessary, preserving at least two valid points |
| `min_free_bytes` | 5 GiB | Preserve working space; full copies require additional headroom |
| `max_run_bytes` | 10 GiB | Primary SQLite database plus WAL/SHM |
| `max_tenant_bytes` | 50 GiB | Hosted tenant live data, checkpoints and filesystem snapshots |
| `compress_payloads` | true | Compress large model request/response strings, preserving exact bytes |
| `durable_writes` | true | Use SQLite `synchronous=FULL` for the writer |
| Hosted `snapshot_keep_last` | 4 | Rotate completed filesystem snapshots after the new catalog pointer commits |

Byte values in YAML are integers; `0` explicitly disables a byte limit. Count
limits must preserve at least two copies. Pins, malformed manifests, changed
files, sidecars and foreign paths are protected. Such files can leave recovery
storage above its configured target; retention logs this rather than sacrificing
the last verified recovery points. A `<run-id>.retention.json` receipt records
the latest world-checkpoint rotation.

Run/tenant admission checks pause before a new simulation tick when a limit is
reached. Hosted advancing controls, new run/connection creation and external
protocol writes return `507` with `storage_capacity_reached`; reads,
pause/stop controls and credential revocation remain available.
These are admission guards, not hard filesystem quotas: an already admitted tick
or request can cross a threshold, and simultaneous tenants need adequate shared
headroom. Size the reserve for peak work and monitor the filesystem itself.

The Hostinger profile disables periodic full world and hosted tick copies.
Litestream streams changes while explicit pause/stop recovery points remain.
Checkpoint and artifact directories sit outside the watched live-run tree, so
Litestream does not recursively back up backup copies.

## Inspect, pin and archive

Commands below are operator tools. Run them from the repository root. Use an
actual run ID and new output paths; none of the copy/archive commands overwrites
or removes its source.

```bash
python -m engine.storage_cli inspect data/runs/RUN_ID.db
python -m engine.storage_cli verify data/checkpoints/RUN_ID_t100.db
python -m engine.storage_cli pin data/checkpoints/RUN_ID_t100.db --reason "Reviewed milestone"
python -m engine.storage_cli unpin data/checkpoints/RUN_ID_t100.db
python -m engine.storage_cli archive data/runs/RUN_ID.db data/backups/RUN_ID.ae.zip
python -m engine.storage_cli restore data/backups/RUN_ID.ae.zip data/backups/restored-RUN_ID.db
```

Pins use a separate `.pin.json` file and also prevent replacement of that world
checkpoint. For a hosted filesystem snapshot, an operator can protect its
artifact directory by placing a `pin.json` file beside its `payload` and
`metadata.json`; hosted retention treats its presence as a pin.

Archives contain one consistent SQLite backup and a checksum/state manifest.
Creation verifies the compressed archive through a real extraction and SQLite
integrity check. Restore rejects extra members, oversized contents, mismatched
checksums, inconsistent run state and existing output paths. Keep the archive's
reported SHA-256 in an independent backup inventory. These archives are private
data and are not research/public export bundles.

## Lossless payload encoding and compatibility

The optional codec stores large `llm_calls.request_json` and `response_json`
values as versioned SQLite BLOBs containing UTF-8 length, SHA-256 and zlib data.
Small or incompressible values stay plain. A framed payload is decoded only after
size, checksum and format checks. Corruption fails visibly. No memory rows are
deleted or replaced by summaries.

Current Store readers, reports, exports and canonical replay/hash readers decode
these fields. The database stays self-contained and its logical scientific
output is unchanged; the physical database hash changes when its representation
changes. Raw SQLite/JSON tools and older application versions do not understand
the BLOB encoding. Produce a verified plain copy before using them or rolling
back the application:

```bash
python -m engine.storage_cli copy data/runs/RUN_ID.db data/backups/RUN_ID-plain.db --encoding plain
python -m engine.storage_cli copy data/runs/RUN_ID.db data/backups/RUN_ID-packed.db --encoding packed
```

Conversion operates on a new consistent copy, verifies the logical model-body
hash, and vacuums only that copy. It preserves every other table. A plain copy can
be much larger; the command checks space during conversion and before vacuum.
Do not replace a running source database with a converted copy. Plan a stopped,
verified migration separately for existing large research runs.

## What remains proportional to use

Compression and rotation eliminate repeated full-history copies. They cannot
keep an unlimited number of agents and all their experiences in a fixed amount
of storage. Completed/inactive runs should be archived to separate storage;
verify restoration before any separately approved removal of their local files.
Streaming backup is a recovery window, not an indefinite version history.
Pinned milestones and full archives provide long-term research preservation.

Litestream is asynchronous. Its one-second sync setting is not a promise of
zero loss after total server failure. The PostgreSQL catalog has a separate,
approximately one-hour backup interval. A recent account or run created after
the last catalog backup can require manual reconciliation with its surviving
SQLite replica. Deployments requiring zero acknowledged loss or coordinated
point-in-time recovery need a stronger database/replication design and a tested
recovery objective before launch.

# Price Discovery Lab: inspector and study workflow

The price lab provides a historical price inspector and local UI/Python workflows for
drafting, validating, running and reporting provider-free paired studies.
Goods and equities share observation, eligibility and analysis contracts.
[G1/F1 induced-value policy benchmarks](market-benchmarks.md) are also available.
The full city integration, checkpoint-derived studies, live-model
policy comparisons and empirical validation remain pending. See the
[implementation log](../plans/2026-09-06-research-city-execution.md).

The CLI and local operator support `preserve_and_resume` studies, committed-day
pauses and original cumulative budgets. Working checkpoints and finalized
results have separate verified private bundle formats. See the
[recovery contract and commands](../plans/2026-09-06-paused-study-resume.md#supervised-runner-and-cli).
The interface's interrupted-job release action only releases its launch slot;
compatible receipted pauses have a separate explicit Resume action.

## Interactive price inspector

Open **Markets → Price lab** in a running local observatory. Select a business
and a 7-, 30- or 90-tick window. The goods and equity inspectors use the same
run, fork and historical cursor. Business/evidence links retain that context.
The URL keeps `view=prices`, `price_firm`, and `price_window` for return visits.

Posted goods prices, period execution VWAP, last executions and their ages are
separate readings. Daily charts leave gaps without executions. The expandable
table provides the exact plotted values and missingness reasons. Invalid daily
evidence remains unavailable and prevents a complete-window VWAP. Historical
order books are explicitly unavailable; current books are displayed quotes.

The read-only projection is `GET /api/v2/workspaces/price-lab`, with `tick`,
`fork_id`, optional `firm_id`, and `window` (1–90). Firm choices exclude future
foundings and retain exited businesses. Choices cap at 500 plus an explicitly
selected existing firm; truncation is visible. The response contains public
price evidence, not account balances or agent prompts. Observer interactions
cannot launch a study or advance the world.

## Compare in the local interface

Open **Experiments → Price studies** with the observer cursor at **Live**.
Choose a saved study to verify its evidence. The library lists local G2/F2
study batches; catalog labels are unverified until that selection finishes.
These independent study worlds are not counterfactual children of the world
currently open. Historical views do not fetch current library artifacts.

Goods and equities receive the same space and treatment selector. The screen
shows arm coverage, available arm means, matched-seed differences, intervals,
per-seed values/execution age and excluded attempts. Arm means can use different
available cohorts; the paired difference uses only matching eligible seeds.
An unavailable price stays unavailable, and stale executed prices retain their
ages. Open the protocol details for snapshot status, provider cost coverage,
source/manifest identities and limitations. Use **Verify again** after local
evidence changes.

**Download private evidence** rechecks the displayed result and verification
identities before publishing a private ZIP. Repeating an unchanged export
returns the same verified artifact. Downloads require operator authority and
carry a SHA-256. The interface limits source evidence to 128 MiB and exposes
at most 1,024 attempt/outcome observations; the CLI supports larger bundles.
Catalog scans are bounded and list at most 100 batches. Checkpoint-based study
forks remain pending.

Working studies retain the same library entry through finalization. Select one
to see assigned worlds, last saved days, pending eligibility and the original
budget. Comparisons are unavailable until finalization. A verified working
checkpoint can be downloaded privately; active, damaged or not-yet-saved
checkpoints cannot. **Open study controls** returns to its originating local
operator job when one exists. Imported/CLI evidence keeps its original controls.

## Create and monitor a local pilot

Under **Experiments → Price studies → Create a study**, choose G2 (input costs)
or F2 (public firm information), seeds, horizon and resource limits. Both presets
measure goods and equities. **Validate draft** preserves an immutable protocol
with its resolved configuration and source identity; it creates no world or
provider call. Review the baseline, intervention, measurement window, targets,
declared primary outcome and limits before choosing **Run independent study**.
Optionally set **Pause after saved days** to stop at a closed checkpoint in the
first world. Leave it blank for an uninterrupted pilot.

These are fresh-genesis pilots using `runs/price-lab-pilot.yaml`: 14 agents,
three firms, scripted policies, zero external provider calls/spend. They do not
fork the world currently being observed. The interface permits 1–5 unique seeds,
3–30 daily ticks, one intervention day, a 10–300 second wall limit and a
32–128 MiB evidence budget; only one study can occupy the local execution slot.
The storage allowance is an uncalibrated planning heuristic: 8 MiB per world plus
256 KiB per world-tick, including replay. A request exceeding its chosen budget
is rejected before draft publication. Actual disk checks occur every 200 ms;
a current write and the final diagnostic report can exceed that threshold.

Draft and job IDs remain in the URL. Reloading a validated draft never launches
it. Launch checks the exact draft digest, run/fork context and source identity.
A repeated idempotency key returns the existing job, including its failure;
a different key cannot reuse an already launched draft. **Edit as a new draft**
creates a new review opportunity. Changing source files after validation
requires a fresh validation, and changing source during execution excludes
affected evidence through the ordinary study guards.

A dedicated supervisor continues independently of the browser and HTTP server.
The UI polls only a selected active job at the Live cursor, shows completed
cell/replay reports and offers **Open verified comparison** when a result exists.
Completion is distinct from valid outcomes: exclusions and missing prices remain
visible in comparison. No automatic retry, resume or provider fallback occurs.

At a clean pause, **Inspect saved progress** opens the library. **Resume saved
study** appears only when the original code, inputs, configuration and evidence
still match and budget remains. It continues the original worlds, finishes
remaining assignments and records a new linked operator job. Original claims
and receipts remain unchanged. Refresh/reload cannot trigger resume; repeated
requests return the same continuation. The wall-time budget includes all active
segments and excludes operator idle time. A changed checkout may block resume
while the frozen checkpoint remains readable and exportable.

After a supervisor exits without a terminal receipt, the job is marked
interrupted once it had started or its 30-second startup allowance expires.
**Release interrupted job slot** first checks the process-owned execution lock,
then retires only the scheduler pointer. Claims, partial databases and logs are
retained. A delayed supervisor cannot start after this release. Running jobs
cannot be released this way; the configured wall/disk limits still apply.
Each world worker watches its supervisor's process handle and exits if that
supervisor dies. Its separate execution lock prevents recovery while it is
still stopping. A hard stop preserves partial evidence without a success receipt.
Use the originating local run context to inspect or recover its job.

The local-only endpoints are under `/api/v2/operator/research`:

| Method and path | Contract |
|---|---|
| `GET /studies` | Bounded catalog; no verification claims for listed titles |
| `GET /studies/{id}?result_sha256=...` | Separate working-progress or finalized-comparison contract; no database/config/private path payloads |
| `POST /studies/{id}/export` | Strict result/verification hash body; create or reuse an exclusively published private bundle |
| `GET /exports/{token}` | Authorized attachment download with `private, no-store` caching |
| `GET /capabilities` | Fixed pilot scope, resource limits and any active job in this run context |
| `POST /drafts/validate` | Strict preset/seed/time/budget request; save a reviewable immutable draft without execution |
| `GET /drafts/{id}` | Frozen protocol, digest, planning allowance and existing job reference |
| `POST /drafts/{id}/launch` | Reviewed `draft_sha256` and a 32-character hexadecimal `idempotency_key`; return 202 with the existing or new job |
| `GET /jobs/{id}` | Context-bound progress, terminal state and comparison reference; no log bodies or private paths |
| `POST /jobs/{id}/recover` | Explicitly release an interrupted supervisor's slot without restarting it |
| `POST /jobs/{id}/resume` | Bind `progress_sha256`, `resume_check_sha256` and a 32-character hexadecimal `idempotency_key`; return 202 with the linked continuation |

All require `run_id`, the current `fork_id` when applicable, `tick=live` and
the existing operator session's `X-CSRF-Token`. Hosted-safe instances deny
access. Stale context/evidence gives 409; unavailable evidence gives a sanitized
422. IDs cannot select arbitrary filesystem paths. Optional local config
`operator_research` supports `enabled`, `data_root` and `out_dir`; defaults are
the checkout's `data/studies` and `reports/out`. Export artifacts live beside
the operator workspace database under `research-exports/`, outside scientific
world tables. Drafts, job claims, progress and private supervisor logs live under
`research-jobs/` beside the workspace database and are ignored by Git. They are
operational artifacts; run databases receive no schema or economic changes.
Expensive file verification runs off the HTTP event loop.

## What can be measured now

| Domain | Measures | Important boundary |
|---|---|---|
| Goods | Observed posted price, successful-sale VWAP, quantity and notional, last-sale age | One firm's comparable product unit; missing sales are not a zero price. Intended and unmet demand are unrecorded. |
| Equities | Last distinct-owner execution and age, execution VWAP, volume/notional, current displayed best quotes and depth | Historical order state is unavailable. Same buyer/seller IDs are excluded; broader beneficial ownership is not recorded. |
| Goods basket | Fixed-quantity complete-basket index and observed baseline expenditure share | Caller must declare comparable items and one currency. Missing members do not reweight survivors. |

Definitions, units, versions and missingness live in the
[metric registry](../../research/metric_registry.py). The
[read-only price reader](../../research/prices.py) returns source event/trade
references. It does not update historical metrics or the database schema.
The existing `cpi` remains the legacy posted-price index described in the
[research guide](../research-guide.md).

## Draft, validate, run

Use the checkout's Python environment. This example creates a unique draft,
checks its complete configuration/input contract without starting a world,
then executes it in a new immutable batch:

```powershell
$priceDraft = "tmp/g2-" + [guid]::NewGuid().ToString('N') + ".json"
.\.venv\Scripts\python.exe -m research.price_catalog G2 --config runs/price-lab-pilot.yaml --output $priceDraft --seeds 1 2 3 4 5 --ticks 30 --intervention-tick 5 --goods-firm-id 2 --equity-firm-id 1 --currency USD
.\.venv\Scripts\python.exe -m research.study_runner $priceDraft --config runs/price-lab-pilot.yaml --validate-only
.\.venv\Scripts\python.exe -m research.study_runner $priceDraft --config runs/price-lab-pilot.yaml
```

Use `F2` with a fresh draft filename for the equally supported financial
information study. `G2` applies an input-cost multiplier; `F2` introduces a
public adverse event about the declared equity firm. Their baseline has no
shock. Both presets measure goods and equity outcomes; each declares one
primary price outcome and labels the other outcomes exploratory.

The default goods/equity targets are separate. The initial eight-tick pilots
targeted firm 1 for both markets and observed no goods sales for that firm.
Those artifacts remain preserved. The revised target choices were informed
by that exploratory observation; they are not held-out or confirmatory choices.
Specify identities/currency explicitly for a different profile.

Draft publication never replaces a previous draft. A second execution creates
a new batch; it does not overwrite source/replay databases or reports. Outputs
are printed as exact local paths under:

```text
data/studies/<key>/<compact-manifest-and-batch-id>/
reports/out/studies/<key>/<compact-manifest-and-batch-id>/
```

Full manifest and batch identities are retained in both `manifest.json` files.
Compact paths accommodate ordinary Windows path-length limits. Generated data,
reports and temporary drafts are ignored by Git.

## Verify and move saved studies

`research.study_results` rechecks the source/replay databases, receipts, frozen
configuration, genesis and outcomes before recomputing the paired summary.
It retains supervisor/worker exclusions even when a database passes replay.
Missing or modified attempts cannot silently become usable pairs. Aggregate
provider costs are marked incomplete when any attempt lacks verified evidence.

```powershell
$studyResult = 'reports/out/studies/<key>/<batch>/results.json'
.\.venv\Scripts\python.exe -m research.study_results $studyResult
.\.venv\Scripts\python.exe -m research.study_bundle export $studyResult tmp/study-evidence.zip
.\.venv\Scripts\python.exe -m research.study_bundle import tmp/study-evidence.zip C:/research-imports/study-001 --expected-sha256 <hash-printed-by-export>
```

Use a new bundle filename and import directory each time. After import, load
the printed result path with `--data-root C:/research-imports/study-001/data`
and `--out-dir C:/research-imports/study-001/reports`. Keep Windows import roots
short enough for the nested run filenames. The importer verifies evidence;
it does not launch agents or execute bundled programs.

The private ZIP preserves original database, manifest and receipt bytes,
including retained failures. A confined path resolver maps their original
absolute paths onto the new roots without rewriting source files. Export
rechecks source identity after copying. Import rejects traversal, duplicate
paths, links, unlisted members, excessive sizes and checksum/proof changes.
Failed imports retain their newly created directory and a failure receipt;
an existing destination is never replaced. Bounds are 8,192 evidence files,
2 GiB of evidence and an 8 MiB index. Loader work also caps assignment,
measurement and bootstrap dimensions; unsupported artifacts fail explicitly.

New studies freeze the model description and declared input bytes before
initialization, up to the smaller of 128 MiB and the declared disk budget.
Earlier studies report `legacy_missing` for snapshots/publication receipts
they never produced. They are not retroactively described as having them.
An internally verified bundle can contain a degraded study: transport
verification does not remove its exclusions or change its conclusions.

These are **private research evidence bundles**. Databases and receipts can
contain agent communications and local paths; they are not sanitized public
exports. The separate public/Parquet export workflow keeps its existing
disclosure rules. Bundles include declared inputs, but not the complete source
checkout, Python runtime or transitive undeclared dataset dependencies; they
support evidence reanalysis, not a claim of self-contained fresh execution.
An externally recorded SHA-256 binds the bytes received. Local checksums alone
do not establish the authenticity of an unknown publisher. The current loader
requires a compatible installed schema, metric and semantics implementation.

## Protocol and limits

The [strict study contract](../../research/studies.py) rejects unknown fields,
unknown metric versions, invalid horizons/seeds, incompatible schemas and
unrecognized intervention parameters. It freezes the resolved configuration,
source-tree identity, model-description hash, seed assignment, intervention and
measurement windows, outcome definitions, analysis method and operational
limits before attempts initialize. Pinned inputs must exist inside their
declared root and match their hashes; fitting inputs cannot double as holdout
artifacts. Configured dataset manifests must themselves be pinned inputs.

This runner supports scripted, provider-free studies with one worker at a
time. It refuses external provider definitions/routes, unsupported policy
families, parallel execution and confirmatory intent. It does not silently
replace a live policy with a scripted one. Provider calls and spend are checked
from actual source records. Source and input identity are checked before and
after each attempt.

The worker is terminated if the campaign wall-time limit is reached. Disk
usage is sampled every 200 ms; the current write and final diagnostic report
can exceed that threshold. It is an operational guard, not an OS disk quota.
Interrupted/failed artifacts are retained, later unstarted cells remain in the
assigned cohort, and incomplete worlds cannot contribute effects. A paused
attempt stops the batch. Resuming it as the same research attempt is not yet
supported; a relaunch creates new attempts.

Each completed attempt must reconcile, finish at the declared horizon and
boundary, and pass an actual recorded replay comparison. Source/replay hashes,
receipt bindings and pending WAL changes are checked before aggregation.
External/participant-influenced attempts remain ineligible.

## Reading findings

The [city observer](city-observer.md) opens both domains for a selected map
business. Its return link preserves the city camera, renderer and filters
while keeping the selected run, fork and tick authoritative.

Reports retain assignment, execution and eligibility counts plus usable pairs
for every outcome. A missing price, incomplete window or unmatched seed gives
a named exclusion and a null estimate when no pair remains. `window_vwap`
weights actual executions across the declared window; a day without trading
does not become a fabricated daily price. Sums are allowed only for flows.

Uncertainty resamples whole world/seed pairs. One pair has no interval;
zero-variance standardization is undefined. A small number of paired worlds
does not support a strong empirical claim even when the descriptive bootstrap
interval is narrow or zero-width. Shared engine randomness may diverge after
treatment, and scripted agents may not respond to a signal. Preserve those
negative findings. These studies are prospective exploratory protocols, not
confirmatory experiments or evidence that the model fits a real economy.

# Price Discovery Lab: inspector and study workflow

The price lab provides a historical price inspector and a Python workflow for
drafting, validating, running and reporting provider-free paired studies.
Goods and equities share observation, eligibility and analysis contracts.
[G1/F1 induced-value policy benchmarks](market-benchmarks.md) are also available.
The full city integration, operator study API, verified bundle export, live-model
policy comparisons and empirical validation remain pending. See the
[implementation log](../plans/2026-09-06-research-city-execution.md).

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

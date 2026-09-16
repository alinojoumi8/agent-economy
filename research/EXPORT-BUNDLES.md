# World OS research bundles

`research.export_bundle.export_bundle` writes a content-addressed Parquet bundle.
The selected hash contract defines authoritative, derived and excluded storage.
Authoritative and derived tables are exported; explicitly excluded tables and
operational columns retain their existing treatment.

| Recorded engine semantics | Default canonical hash | Default export contract |
|---|---|---|
| 1-8 | v1 | v1 |
| 9-14 | v2 | v1, preserving the existing export format |
| 15-16 | v3 | v3 |
| 17 | v4 | v4 |
| 18 | v5 | v5 |
| 19 | v6 | v6 |
| 20 | v7 | v7 |
| 21, unregistered draft fixtures only | v8 | v8 |

An explicit `contract_path` can select the compatible v2 contract for an earlier
world. Semantics 15 and later require their own contract; downgrades are rejected.
Unknown tables/columns and populated household, time, estate or population journals
hidden behind an older contract
also cause rejection. The v1-v7 contract files remain unchanged.

The v8 label requires the maintained contract definitions. Modified classifications,
column exclusions, JSON treatment or privacy rules are rejected under that label.

The v8 contract includes residence history, the resident census, movements,
adult assents, commitment endings, the declared schedule and its input receipts.
These are authoritative records, including their structured JSON and event links.
Population Parquet retains simulated person IDs, household/care terms and request
identifiers for research audit. The existing default privacy profile redacts
private communication bodies, message-derived memory text and model payloads,
and pseudonymizes the specific communication columns listed in the contract.

Exporting v8 does not register schema 26 or enable Semantics 21 in normal runs.
See the [population evidence and admission boundary](../docs/plans/2026-09-09-open-population-boundary.md#population-research-exports).

The exporter bounds row batches, record size, DuckDB memory, disk work and elapsed
time through `ExportLimits`. It reads Parquet back against a single source
snapshot before publishing `manifest.json` last. The manifest binds canonical
hashes, file hashes, schema, row counts and privacy counts. Resource statistics
do not affect bundle identity. Use a closed immutable source when exporting a
completed research artifact:

```python
from contextlib import closing
from engine.store import open_read_only_connection
from research.export_bundle import export_bundle, validate_bundle

with closing(open_read_only_connection(source_path, require_closed=True)) as source:
    bundle = export_bundle(source, output_root)
    receipt = validate_bundle(bundle, database=source)
```

`validate_bundle(bundle)` checks archive consistency. Supplying `database=source`
also verifies canonical identity and each transformed source row; a rewritten
archive with recomputed checksums cannot pass that comparison.

Example DuckDB query for a population bundle:

```sql
SELECT tick, closing_residents, known_living_outside, total_known_living,
       departures, returns, resident_deaths
FROM read_parquet('bundle-*/population_resident_census.parquet')
ORDER BY tick;
```

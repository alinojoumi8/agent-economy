# World OS research bundles

`research.export_bundle.export_bundle` writes one content-addressed directory. Every world
table is classified by `hash-contract-v1`; authoritative and derived tables become Parquet,
while operational/research-only tables remain excluded. Private communication subjects,
bodies, message-derived memory text, model request/response payloads, and ambient message
text are absent from the default export. Communication participant IDs are deterministically
pseudonymized within a bundle.

The bundle is usable only after `manifest.json` appears. That manifest is published last and
contains the canonical authoritative hash, per-file hashes, schemas, row counts, redaction
counts, and pseudonym counts. `validate_bundle(path)` rejects interrupted or modified output.

Example DuckDB query:

```sql
SELECT tick, kind, subject_type, subject_id
FROM read_parquet('bundle-*/events.parquet')
ORDER BY tick, id;
```

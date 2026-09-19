# Population project gates — hosted admission

The local Python matrix and the remaining hosted integration tests have passed.
Native demographic acceptance, W5 completion and W6–W9 remain open. Goods and
equity price discovery retain equal priority.

This supersedes the earlier Docker and local-matrix status in the
[project-gate record](2026-09-10-population-project-gates.md). It does not change
the [native verification contract](2026-09-09-full-campaign-verification.md).

## Passing evidence

| Gate | Result |
|---|---|
| Windows / Python 3.11 | 3,329 distinct tests with passing evidence; 16 resolved matrix slots |
| Windows / Python 3.12 | 3,329 distinct tests with passing evidence; 16 resolved matrix slots |
| Linux / Python 3.11 | 3,329 distinct tests with passing evidence; 16 resolved matrix slots |
| Linux / Python 3.12 | 3,329 distinct tests with passing evidence; 16 resolved matrix slots |
| Hosted Linux / Python 3.12.14 | Eight passed; zero skips; zero failed phases; all 24 setup/call/teardown records retained |

The hosted cases are six PostgreSQL authorization/isolation cases and two MinIO
snapshot/restore cases. They verify restricted runtime roles, tenant separation,
expired sessions, scoped discovery, login and redacted audit, limited quota
updates, immutable snapshots, exact SQLite restoration and denied object deletion
by the scoped storage identity.

There are 3,337 distinct selected test IDs with passing evidence across these
declared gate environments. The eight hosted cases ran once in Linux Docker;
they were not rerun in each local environment. Historical skips remain unchanged.
Separate scanner passes close two scanner skips in each Python 3.11 environment.
Original interrupted attempts remain separate from successful full replacements;
partial results are not added to passing counts.

The real production-backend city workflow, 264 dashboard checks, TypeScript,
Node 22 build, dependency audits and 121 critical browser checks retain their
separate passing results. Native demographic outcomes and human usability
acceptance remain separate. Existing Starlette/httpx deprecation and frontend
bundle-size warnings remain recorded.

## Hosted execution and launcher correction

Docker 29.7.2 responded after the user's availability update. The controller used
the frozen source archive, declared service tags with recorded image identities,
private credentials, an internal network and no host port mappings. Application
and test containers ran as UID/GID 10001.

The first invocation stopped after 1.907 seconds while inspecting MinIO image
metadata: its configuration omitted optional `User`, so direct lookup failed.
No containers or tests had started. The inspected continuation uses an optional
key lookup; the application's required `10001:10001` identity assertion remains.
The original controller, failed receipt and logs are retained unchanged.

The continuation kept the original gate identity and deadline. Cumulative elapsed
time, including diagnosis, was 259.540 seconds against the original 1,200-second
allowance. Tests took 3.973 seconds; peak observed test-tree memory was 102,363,136
bytes against a 16 GiB limit. The 40 GiB free-space floor was maintained.

All five owned containers finished or were stopped and retained. Independent
inspection confirmed ownership, no running containers, exit code zero and no
out-of-memory termination. Images and the private network remain retained. No
shared Docker service was restarted and no scientific artifact was deleted.

The successful continuation command was:

```powershell
.\.venv\Scripts\python.exe -X utf8 tmp\continue-population-hosted-metadata.py
```

This records a completed invocation, not a command to run again. The launcher
refuses reuse of the retained continuation directory.

## Source and retained evidence

The gate tested the 1,190-file snapshot on `codex/research-city-price-lab`, HEAD
`ca6c1cf6e98356994e6bba1277fc9d03b2fa223d`. The source-manifest SHA-256 is
`fb9d73ca527f99d0f1cee8bacda7c177f252245fcb52e418b858ca37e2857880`.
Source hashes and modification times matched before and after execution; staging
was empty. This document and its two routing updates are subsequent documentation
changes, recorded separately from that tested snapshot.

- [Combined hosted closure](C:/Users/matri/.codex/tmp/ae-089e251d/hosted-gate-closure.json), SHA-256 `f8d486762c14ddd11bf5a361f1718b925f48e6af7b62a330a6c2a99f60bd4f9c`.
- [Completed hosted receipt](C:/Users/matri/.codex/tmp/ae-089e251d/hosted-integration-attempt/metadata-continuation/receipt.json).
- [Hosted test results](C:/Users/matri/.codex/tmp/ae-089e251d/hosted-integration-attempt/metadata-continuation/client-evidence/meta.json).
- [Stopped-container verification](C:/Users/matri/.codex/tmp/ae-089e251d/hosted-owned-container-final-state.json).
- [Local matrix closure](C:/Users/matri/.codex/tmp/ae-089e251d/full-matrix-closure.json).
- [Current operational handoff](C:/Users/matri/Documents/myprojects/agent-economy/tmp/population-full-matrix-2026-09-10-status.md).

## Remaining execution order

1. Resolve native horizon, productive second-generation behavior, full-prefix
   comparison/export and remaining earlier acceptance under the preserved
   [W5 contract](2026-09-09-w5-acceptance-audit.md). The source ended at day 11,356
   of 14,600 after its four-hour allowance. The interrupted verifier has no final
   comparison/export/readback result; its last logged progress leaves at most
   2,435.437 seconds of the original replay allowance. Keep the original source,
   frozen runtimes and recovered copy unchanged. Docker passing does not reset
   either resource allowance or satisfy these scientific gates.
2. Keep schema 26/Semantics 21 unregistered until full admission passes. Do not
   mark W5 complete based only on the matrix and hosted results.
3. After W5 and earlier acceptance close, implement the saved
   [W6 education design](2026-09-10-education-integration.md), then W7–W9 in order.
   The complete [execution plan](2026-09-06-research-city-execution.md) remains
   the governing scope, with goods and equities equally represented.

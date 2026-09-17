# Recovery, limits and operations

This is the operator runbook for the Hostinger-style Docker deployment. The
same controls apply on another Linux VPS. Repository drills use disposable
local infrastructure; they are not evidence of an off-server production backup,
public TLS, production capacity or an independent release approval.

## Local rehearsals

From the repository root, with the locked Python dependencies and Docker:

```bash
python -m scripts.docker_preflight
python -m scripts.run_ops_drill --output tmp/recovery-drill
python -m scripts.alert_delivery_drill --output tmp/alert-drill
```

The first drill builds a disposable Linux test image, starts two distinct
PostgreSQL 17 servers, creates two tenants and an external actor, executes a
scripted action, and fences the source writer. It verifies the remote Litestream
watermark, uploads/downloads a checksum-verified catalog dump through SFTP, and
restores into the second server and a fresh world directory. It checks account
balances and ledger reconciliation, tenant isolation, restored agent credentials,
the original execution receipt, idempotent retry and successful next-tick resume.
Finally it exercises the recovered app over a real loopback TLS socket: six
rounds of 100 authenticated requests, eight concurrent requests and a two-second
p95 threshold, with ten seconds between rounds. This is a short recovery soak,
not a production endurance test. All provider decisions are scripted and free.

The second drill uses the production Prometheus alert expressions and
Alertmanager routing, with evaluation/grouping delays shortened for testing.
It injects an API scrape failure and requires both firing and resolved webhook
notifications. The receiver is disposable and cannot notify a real person.

Both commands require fresh output directories, write redacted `receipt.json`
files, and remove only their own randomly named containers/networks and anonymous
test volumes. Private diagnostic logs can contain connection errors; review them
before sharing. CI runs both drills and uploads only the redacted receipts.

## Backups and recovery points

Follow [the storage deployment guide](hostinger-vps.md) for verified host keys,
separate catalog/run writer identities and read-only run restore credentials.
The destination must be a different server with independent administration.
Run replicas use one-second sync, daily snapshots and seven-day retention.
Catalog dumps run hourly and retain the latest 24 plus seven daily and four
weekly recovery points. Local full snapshots retain four copies.

Asynchronous replication is not zero-loss storage. Catalog and world recovery
points can differ, and hourly catalog backups can lose recent account changes.
For a planned cutover, close admission, pause all worlds, fence the old app,
verify each run's latest committed tick is restorable, then take a final catalog
backup. Record the catalog checksum and each world's tick in the change record.
Do not resume the old writer after restoring a replacement. For an unplanned
failure, record the actual lost interval, reconcile catalog/world identities,
and revoke/reissue credentials whose post-backup revocations may have been lost.

On the replacement server, use the exact approved image, migration history and
configuration, provision restricted PostgreSQL roles, restore the verified
catalog dump into an empty database, and let read-only Litestream recovery load
each missing world. Verify both tenants' login/isolation, balances, original
action receipts and idempotent retry before enabling ingress. A second submission
with a different idempotency key is a new action, not a recovery retry.

Before public admission, run this procedure against the actual backup server
and a replacement VPS. Keep an independently protected recovery point on the
backup server: writer credentials necessarily have retention deletion rights.

## Bounded execution

Hosted `start` now defaults to 100 ticks and accepts at most 1,000 per request;
larger requests return 422 before controller dispatch. An administrator can
start another bounded batch. This is a per-start limit, not a lifetime quota.
External agents cannot administer the run. Pause and stop remain available when
storage admission fails. Desktop simulation controls are unchanged.

Existing controls include tenant connection quotas enforced under a PostgreSQL
lock, credential request limits, bounded request bodies, bounded concurrent
world reads, loaded-run limits, per-tenant/run disk limits, bounded provider
concurrency, and deterministic fallback for agents that miss their turn. The
default external profile allows 240 credential requests/minute. The gateway
tests include 100 offline actors and prove their fallback does not wait for
network clients. Keep public ingress request/connection limits and timeouts
appropriate for the chosen VPS; application quotas do not prevent network DDoS.

The hosted allowlist currently uses scripted providers: external agents pay for
their own models. The provider-budget suite proves durable call/token/spend
reservation behavior for explicitly configured budgeted runs, but that research
budget is not automatically a shared hosted billing account. Do not introduce
paid hosted profiles without a shared durable spend cap and provider-side hard
limits. A per-run estimate alone is not a platform-wide bill cap.

For capacity evidence, `python -m hosted.load_test --help` describes the bounded
two-tenant probe. Supply passwords through named environment variables, use the
real HTTPS origin and immutable `--build-ref`, and require `--max-p95-ms 2000`
(or an explicitly agreed SLO). A successful HTTP response that exceeds this
latency budget fails the probe. Repeat at the intended arrival rate over a
24-hour staging soak while recording CPU, memory, disk growth, backup freshness,
agent fallback and errors. The local short soak does not certify VPS capacity.

## Alerts

Prometheus now forwards alerts to a private Alertmanager service. Put an
HTTPS URL for an Alertmanager-compatible receiver in the ignored file
`deploy/hostinger/secrets/alert_webhook_url`. This is a URL file, not YAML or a
shell environment assignment. Restrict its permissions and make it readable
by the Alertmanager container user. Compose refuses to invent a missing file.
Do not use a generic Slack incoming URL: the receiver must accept the
Alertmanager webhook schema, or configure the native integration explicitly.

Alerts cover API/backup process outages, catalog backups older than 90 minutes,
Litestream errors and disk-full signals, HTTP server errors and notification
delivery failures. Catalog freshness is exported on the private port 9091;
missing, corrupt or future-dated receipts fail closed. No secret, tenant name,
backup path or database credential is included in that metric.

Test delivery to the selected real destination before public use. It is not
configured by the local drill. Arrange an independent external uptime check:
Prometheus and Alertmanager on the same VPS cannot notify you when that entire
VPS or its network dies. Do not expose their administrative ports publicly.

## Upgrade and rollback rehearsal on staging

1. Record the current and candidate image digests and catalog migration versions.
   Retain the previous image. Close admission, pause/fence writers and capture a
   verified paired recovery point as described above.
2. Restore that point into an isolated staging stack first. Apply the candidate
   migrations once and again to prove idempotence, start the candidate image,
   and require readiness, tenant isolation, ledger and action-retry checks.
3. Stop the candidate writer before starting the previous image. Only reuse the
   migrated database if backward compatibility is explicitly proved. Otherwise
   restore the paired pre-upgrade backups into another empty stack. Never run a
   down-migration blindly and never point two writers at one world.
4. Require the same readiness and action-retry checks on the rollback image.
   Record elapsed recovery time, selected tick and any lost interval. Start the
   candidate again and run the staging soak. Only then reopen admission.

Use the existing deployment Compose command/environment for these steps;
`AGENT_ECONOMY_IMAGE_TAG` must identify the retained immutable release. Do not
use `compose down -v`, factory reset or volume pruning as a rollback. An image
restart without the above compatibility/data checks is not a rollback proof.
This repository change adds no database schema migration. Actual old/new-image
rollout and rollback on the selected host remain a release gate.

## Docker Desktop startup failures

Run `python -m scripts.docker_preflight` before Docker work. It probes the engine
with a timeout and leaves a healthy engine untouched. On Windows, `--start`
starts a stopped Desktop once in a hidden window; if Desktop/backend is already
running, it waits instead of launching another copy. Failure stops dependent
work. It never removes sockets, resets data, prunes volumes or kills a backend.

If Desktop crashes, preserve timestamped Desktop diagnostics and an inventory
of containers/volumes, and inspect the first fatal startup error. Stale socket
errors and benign idle-event EOF messages are different symptoms. Coordinate
any engine/WSL restart with other running projects. The guard reduces duplicate
startup races; it is not a claim that an unreproduced Desktop defect is repaired.

# Hostinger VPS deployment and recovery

This deployment runs on a Linux Hostinger VPS with Docker Compose. It uses
PostgreSQL for the hosted control plane and SQLite for individual worlds.
Litestream 0.5.17 streams SQLite changes to a separate SFTP server. No Amazon
account or Amazon-hosted service is required. Hostinger documents Docker VPS
support in its [Docker template guide](https://www.hostinger.com/support/8306612-how-to-use-the-docker-vps-template-at-hostinger/).

Use a separate machine or storage service for SFTP. A second directory, Docker
volume, or SFTP process on the site VPS does not protect against losing that VPS.
The [storage guide](storage-and-recovery.md) explains memory preservation,
limits, compatibility and the archive commands.

## Prepare the deployment

1. Check out the reviewed release on the VPS. This storage change is developed
   on `codex/hostinger-storage-recovery`; merging and production deployment are
   separate steps.
2. Point the site's domain at the VPS. Set the exact HTTPS origin and host.
3. Create the three SFTP accounts described below on the separate server.
   Keep run backups and catalog backups in separate chroots. Permit file
   timestamps and rename operations for writers; recovery access must be read-only.
4. Generate three independent SSH client keys. Install each public key on its
   corresponding backup account. Do not reuse a key between the accounts.
   Verify the server's public host key through its trusted console/provider;
   a network key scan alone does not establish its identity.
5. Save the private keys as `backup_key`, `restore_key`, and `catalog_key` in the
   ignored `deploy/hostinger/secrets/` directory. On Linux give each owner UID/GID
   `10001:10001` and mode `0600`; containers use that unprivileged identity.
   Keep the directory private and keep independent recovery copies of the keys.
6. Copy [the environment template](../deploy/hostinger/.env.example) to the
   ignored `deploy/hostinger/.env` and fill every blank. Use independent strong
   PostgreSQL passwords. `AE_BACKUP_SFTP_HOST_KEY` is the algorithm plus base64
   public host key; `AE_BACKUP_SFTP_PATH` is the dedicated absolute directory.

## Backup access boundaries

| Container | SSH private key | SFTP account | Access |
| --- | --- | --- | --- |
| `app` | `restore_key` | `AE_RESTORE_SFTP_USER` | Read-only access to run replicas |
| `litestream` | `backup_key` | `AE_BACKUP_SFTP_USER` | Write and retain run replicas |
| `catalog-backup` | `catalog_key` | `AE_CATALOG_SFTP_USER` | Write and retain catalog dumps in a separate chroot |

The [SSH server configuration example](../deploy/hostinger/sshd-backups.conf.example)
uses `ae_run_writer`, `ae_run_reader`, and `ae_catalog_writer`. Set the environment
values to the actual account names. Both run accounts see the same run directory;
`AE_BACKUP_SFTP_PATH` could be `/backup`. Set `AE_CATALOG_SFTP_PATH` to a directory
inside the catalog account's separate chroot, also possibly `/backup`. These paths
refer to different server directories even when their names inside each chroot match.
The catalog tool creates its `catalog` child there.

All chroot roots and parents must be owned by root and must not be writable by
the SFTP accounts. Provision the run `/backup` directory with the writer as owner,
a group shared with the reader, and mode `2750`; future directories inherit that
group. The writer's `0027` umask keeps replicas group-readable and private to those
accounts. The reader must be forced to `internal-sftp -R`, with shell execution,
forwarding and password authentication disabled. Keep authorized-key files outside
writable backup directories. Restrict SSH network access to the site and recovery
operators. Validate the SSH configuration before reloading it, then prove the
reader can restore a newly written replica and cannot create, replace, rename or
delete files. The app must not have access to the catalog tree.

The catalog service now uses `agent_economy_backup` and its independent
`CATALOG_BACKUP_PASSWORD`. This role has SELECT on the application's `public`
schema and `BYPASSRLS` so dumps include every tenant, with no superuser, table-write
or role-management privileges. Default privileges cover future tables created by
the migration administrator. It is deliberately not a member of `pg_read_all_data`,
which would also expose protected system catalogs, including database password hashes.
The initialization script runs automatically for a new PostgreSQL volume. When
upgrading an existing installation, load the new environment/container definition,
then run `exec postgres /bin/sh /docker-entrypoint-initdb.d/002_backup_role.sh` with
the Compose options below before starting `catalog-backup`. No data migration or
memory deletion is involved. Changing environment values alone does not rotate an
existing database role's password.

These permissions use PostgreSQL's [schema grants](https://www.postgresql.org/docs/17/sql-grant.html)
and OpenSSH's [read-only SFTP option](https://man.openbsd.org/sftp-server.8).

## Start the services

From the repository root:

```bash
docker compose --env-file deploy/hostinger/.env -f deploy/hostinger/compose.yaml config --quiet
docker compose --env-file deploy/hostinger/.env -f deploy/hostinger/compose.yaml build
docker compose --env-file deploy/hostinger/.env -f deploy/hostinger/compose.yaml up -d
docker compose --env-file deploy/hostinger/.env -f deploy/hostinger/compose.yaml ps
```

The build downloads official Litestream binaries for Linux x86-64/ARM64 and
verifies the pinned SHA-256. The runtime and backup containers share the same
release. Migrations must succeed and Litestream must start before the app starts.
The app exposes only Caddy's TLS endpoint; PostgreSQL and metrics have no public
ports. Outbound networking permits SFTP and explicitly configured agent/provider
connections. Litestream needs write access to SQLite's directory for its WAL
and replication state.

Bootstrap the first administrator using a private terminal and an environment
variable or the CLI's hidden prompt, as described in the
[operator runbook](operator-runbook.md). For this deployment use
`-f deploy/hostinger/compose.yaml --env-file deploy/hostinger/.env` with the
`bootstrap` service and `/app/config/hosted.migrate.docker.yaml`. Existing
PostgreSQL volumes keep their stored passwords; changing an environment file
alone does not rotate those passwords.

## Backup behavior and monitoring

- SQLite: continuous SFTP replication, nominal one-second sync, daily full
  Litestream snapshot and seven-day retention. Litestream manages its own
  dependent incremental files. Never apply generic age-based deletion to an
  active replica's individual LTX files.
- Local recovery copies: four verified world checkpoints and four completed
  hosted filesystem snapshots per run, with pins protected. Full tick copies
  are disabled in this profile.
- PostgreSQL: an hourly custom-format dump is uploaded, downloaded again, and
  checksum-verified. Retention keeps the newest 24 copies, one per day for the
  newest seven distinct days, and one per week for four distinct weeks (at most
  35 copies). A fixed pending-upload slot prevents failed uploads accumulating.
- Docker logs: three 10 MB files per service. Prometheus retains up to seven
  days or 1 GB. Persistent run/catalog data remains subject to its own policy.

Inspect service health and private logs after startup:

```bash
docker compose --env-file deploy/hostinger/.env -f deploy/hostinger/compose.yaml logs --tail 100 litestream catalog-backup
docker compose --env-file deploy/hostinger/.env -f deploy/hostinger/compose.yaml exec catalog-backup python3 /opt/catalog_backup.py health
```

Only one catalog backup writer may use a destination. For a one-off backup,
stop the scheduled `catalog-backup` service, run `catalog-backup once` with
`docker compose run --rm --no-deps`, then start the service again. Do not run a
second stack against the same backup namespace.

Litestream's container health check proves its metrics process is reachable,
not that every remote write succeeded. Prometheus loads the supplied sync,
remote-write, disk-full and compaction-failure rules. Connect those alerts and
the catalog container's health to the operator's monitoring destination before
launch. No notification destination is preconfigured. Check capacity on both
the VPS and backup server. Remote storage quotas must leave room for complete
snapshots and incremental compaction.

Paused and stopped databases remain in the watched tree so their latest state
continues to be backed up. Deleting a watched database leaves its remote replica
behind. Archive and verify permanently retired runs, then handle their remote
replica directory as an explicit retirement operation. Indefinitely retaining
every abandoned replica defeats a storage budget.

## Recovery

For a process restart with the live volume present, SQLite opens its committed
database and WAL. For a missing live database, the supervisor restores the
matching stream into a private temporary file. It verifies SQLite integrity,
schema and the run ID, then publishes without replacing an existing database.
A failed stream restore does not fall back to an older full snapshot. Recovered
runs remain paused, with external connections reconciled against the catalog.

For loss of the site VPS:

1. Provision a replacement VPS with the reviewed application release, protected
   environment file and the three backup SSH keys. Keep the app and Litestream stopped
   during catalog recovery.
2. Start only PostgreSQL. It initializes the current app/supervisor/backup roles from
   the protected passwords. Use a new, empty catalog database for recovery;
   keep any previous damaged volumes for investigation.
3. Fetch a named catalog dump to a private host directory with the backup image:

   ```bash
   docker compose --env-file deploy/hostinger/.env -f deploy/hostinger/compose.yaml run --rm --no-deps \
     -v /srv/ae-recovery:/recovery catalog-backup fetch \
     --name catalog-YYYYMMDDTHHMMSSZ.dump --output /recovery/catalog.dump
   ```

   The destination directory must be writable by UID 10001. Fetch verifies the
   downloaded checksum and that `pg_restore --list` can read it. Restore into the
   empty database with PostgreSQL 17 `pg_restore --exit-on-error`, retaining
   ownership/grants for the recreated `agent_economy_app` and
   `agent_economy_supervisor` roles. Do not use `--no-owner` as a shortcut: the
   hosted privilege boundary relies on the intended ownership/grants.
4. Run the migration check, then start Litestream and the app. Active catalog
   runs recover their missing SQLite databases from the stream. Other runs
   recover when opened. An unavailable or mismatched replica requires operator
   investigation; do not create an empty replacement run under its identity.
5. Verify tenant membership, agent ownership, last completed tick, memories,
   action history, ledger reconciliation and a recorded replay before resuming
   traffic. Catalog and SQLite backups have different recovery times; reconcile
   catalog changes after the selected dump and disable/reissue any credentials
   whose revocation happened after that dump.

An explicit full-snapshot restore using existing hosted operations is a deliberate
rollback. Record its chosen point and expected lost interval. It must not be
mistaken for recovering the newest stream. Restores that exceed disk budgets
need more capacity or a reviewed policy adjustment.

## Repeatable recovery checks

Run the real-binary drill on Linux, WSL with a Linux filesystem, or CI:

```bash
python -m pip install --require-hashes -r requirements.lock -r tests/requirements-storage.lock
python deploy/hostinger/install_litestream.py --output /tmp/ae-litestream
AE_LITESTREAM_BIN=/tmp/ae-litestream python -m pytest -q tests/test_litestream_recovery.py
```

This starts a disposable loopback SFTP server, creates a database after the
watcher starts, commits memories and actions into WAL, and restores both the
initial and subsequent changes. Separate tests cover corrupt/wrong-identity
restores, archive round trips, replay, quotas and retention failures. No real
Hostinger account or production data is used. Litestream 0.5.17's native Windows
binary failed directory fsync in local verification; use Linux for this service.

The storage CI job also builds the catalog backup image and tests a real
PostgreSQL 17 dump, SFTP upload/download, and restore into a second database,
including all tenant rows under RLS, table ownership and grants. It also proves
the backup role cannot delete/drop tables, read PostgreSQL password hashes, or
assume the superuser role. The Litestream SFTP drill restores with a separate
read-only identity. To repeat the disposable catalog drill on Linux
with Docker available:

```bash
docker build -f deploy/hostinger/Dockerfile.catalog-backup -t ae-catalog-backup:drill .
AE_CATALOG_BACKUP_IMAGE=ae-catalog-backup:drill python -m pytest -q tests/test_catalog_backup_integration.py
```

Before public use, repeat the drill with the actual separate backup server and
restore a real PostgreSQL catalog into an isolated replacement stack. Repository
tests and rendered Compose configuration do not prove the chosen server's SSH
permissions, off-server durability, TLS, capacity or complete disaster recovery.
The existing hosted/external-agent rollout requirements remain in effect.

Remote writer accounts necessarily retain deletion rights for retention. Protect
backup-server administration separately and keep server-side recovery points that
these writer accounts cannot erase. The read-only app credential limits damage
from an app compromise; it does not protect against compromise of the backup server.

Configuration follows Litestream's official
[directory watcher](https://litestream.io/guides/directory-watcher/),
[SFTP](https://litestream.io/guides/sftp/) and
[retention reference](https://litestream.io/reference/config/).

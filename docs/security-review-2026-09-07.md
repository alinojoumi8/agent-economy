# Storage and hosted security review — 7 September 2026

Scope: `codex/hostinger-storage-recovery`, starting at `caae404`, including the
checkpoint codec, retention/archive paths, Hostinger deployment, SFTP recovery,
catalog backups, and the hosted authentication paths that protect these services.
The review followed ECC's security-review workflow. It used source tracing,
reproduction tests, dependency/secret scans, and disposable recovery services.
No production account, real agent database, or original research worktree was changed.

## Findings and fixes

| Severity | Issue | Fix and evidence |
| --- | --- | --- |
| Medium | Refresh credentials were accepted as bearer credentials by REST and MCP, bypassing access-token lifetime and rotation rules. | Authentication now permits only personal/access credential kinds. Tests reproduce the former HTTP 200 and require HTTP 401 with no credential writes; refresh exchange still works. |
| Medium | Unauthenticated agent writes could trigger tenant disk scans and distinguish storage exhaustion before credential validation. | Read-only credential/PKCE validation precedes storage checks. Authentication and token consumption are repeated after asynchronous admission. Invalid credentials skip scans; capacity rejection preserves an unconsumed authorization code. |
| High | Hosted GET bodies bypassed the request limit, while the agent proxy could buffer those bodies before validating the token. | The 64 KiB limit now covers every HTTP method before routing or proxying. An oversized GET is rejected with HTTP 413. |
| High | Anonymous OAuth registrations could create an unlimited number of persistent catalog rows outside tenant run quotas. | Bounded in-memory ingress accounting allows 20 requests per peer and 300 total per hour, plus a 10,000-record persistent ceiling. PostgreSQL admission uses a transaction advisory lock so concurrent workers cannot exceed the ceiling. Existing clients are preserved. |
| Medium | A valid credential could append an audit row for every request rejected by the rate limiter, growing a paused run through rejected traffic. | Denial auditing is bounded to one row per connection/minute. Requests already over their rate limit also skip storage scans. The regression test sends repeated rejected requests and proves no further database changes. |
| Medium | The web app held the backup writer key, all backup namespaces shared that identity, and the catalog job used the PostgreSQL superuser password. An app or backup-container compromise could destroy recovery data or obtain unnecessary database privileges. | Separate run writer, read-only run recovery and catalog writer keys/accounts; separate catalog chroot; non-superuser catalog read role. Deployment tests check secret separation, the SFTP drill restores through a read-only identity, and the real PostgreSQL drill checks RLS completeness and forbidden writes/privilege escalation. |

The PKCE validator also rejects malformed/non-ASCII verifiers without a server
exception. The static scanner's SHA-1 finding was a false positive: `_seed` only
controls deterministic simulation variation. It is now explicitly marked
`usedforsecurity=False`, preserving historical seed values exactly.

The refresh-token boundary follows [OAuth 2.0 section 1.5](https://datatracker.ietf.org/doc/html/rfc6749#section-1.5).
The anonymous-registration controls address the resource-exhaustion risk described
in [dynamic registration security considerations](https://datatracker.ietf.org/doc/html/rfc7591#section-5).
The backup role uses [PostgreSQL schema grants](https://www.postgresql.org/docs/17/sql-grant.html),
and the SSH template uses [OpenSSH read-only SFTP](https://man.openbsd.org/sftp-server.8).

## Validation

- Reproduction before fixes: all three initial regression tests failed, confirming
  refresh-token acceptance, a pre-authentication storage scan, and the GET limit bypass.
- Final Linux credential, replay, compression and real recovery tests:
  `python -m pytest -q tests/test_security_review.py tests/test_external_agent_gateway.py tests/test_recorded_replay_golden.py tests/test_payload_storage.py tests/test_litestream_recovery.py tests/test_catalog_backup_retention.py`
  — 57 passed with pinned Litestream 0.5.17 and locked optional SFTP dependencies.
  The drill restores incremental memory/action history through a read-only SFTP
  identity; separate tests reject replacement/deletion attempts.
- `python -m pytest -q tests/test_acceptance.py tests/test_security_review.py`
  — 58 passed. Two acceptance tests now wait up to ten seconds for the background
  run/report to finish and assert it stopped before checking the result. Their
  former 100 immediate status reads could finish before that work completed.
- [Final CI at `1f3fc11`](https://github.com/alinojoumi8/agent-economy/actions/runs/34115703715)
  passed all enabled jobs: 82 storage/security tests, one real PostgreSQL 17 dump,
  SFTP fetch and restore, the core/smoke suites, 194 dashboard unit tests, 47
  Chromium checks, typechecking, notices and the production build. Compose and
  both Docker image builds/CLI smokes and all eight hosted PostgreSQL/object-store
  integration cases also passed.
- The earlier catalog-role test failed because `pg_read_all_data` exposed
  `pg_authid`. Explicit grants on the application's schema fixed this. The test
  now proves that cross-tenant rows survive backup/restore, while table writes,
  password-hash reads and privilege escalation are denied. All eight real hosted
  PostgreSQL/object-store cases also passed in the final run's
  [integration job](https://github.com/alinojoumi8/agent-economy/actions/runs/34115703715/job/101721872497).
  The earlier catalog-role failure is superseded by the passing corrected test.
- `uv tool run --from pip-audit pip-audit -r requirements.lock --disable-pip`,
  the same audit of `tests/requirements-storage.lock`, and
  `npm audit --audit-level=moderate` — no known vulnerabilities reported.
- `bandit -r agents engine hosted server deploy/hostinger -lll -f json -o tmp/security-bandit-final.json` — no
  high-severity findings. The medium/high-confidence candidates from `-ll -ii`
  were reviewed: SQL structure comes from internal constants/allowlisted fields,
  the temporary state file is inside the private backup container, and the
  installer downloads a fixed official HTTPS release with a pinned checksum.
- `gitleaks git --config .gitleaks.toml --redact --no-banner .` — no leaks in
  230 commits (60.37 MB); subsequent changes were also scanned before commit.
  Both pinned Gitleaks allowlist regression tests passed separately on Windows.
- Compilation, `python -m pip check`, required dataset verification and diff
  checks passed. Existing Starlette TestClient deprecation and dashboard chunk
  size warnings remain; the committed dashboard bundle matches a fresh build.

The final Linux Python 3.12 full suite passed in eight CI shards: **1,618 passed,
16 skipped, zero failures/errors**. Each shard ran
`python -m pytest tests/ -q -p scripts.pytest_shard --ci-shard-index N --ci-shard-count 8`
for `N=0..7`. The skips require optional SFTP dependencies, external services,
the Litestream binary or pinned Gitleaks; the corresponding cases passed in the
separate recovery/integration jobs and pinned Windows scanner tests above.

The initial four-shard security run had one acceptance timing failure (1,618
passed, 13 environment skips). The subsequent acceptance-module run exposed the
same insufficient polling in a second test. Both waits were fixed before the
final complete suite; economic mechanics and production run control were unchanged
by those test corrections.

## Deployment and review limits

The [Hostinger guide](hostinger-vps.md) documents the three SSH identities, the
new `CATALOG_BACKUP_PASSWORD`, initialization for existing volumes, and recovery
checks. The read-only restriction must actually be installed on the separate
SSH server; mounting a key read-only in Docker is insufficient. Verify newly
created replica readability and denied writes with the deployed accounts.

The supported server is one process. The anonymous-registration rate limiter is
per process, and shared proxies/NAT can group clients; the PostgreSQL total cap
is durable across processes. These controls complement deployment-level traffic
limits. No existing OAuth clients, memories or checkpoints were deleted.

Storage limits remain admission checks: an already admitted operation can grow
beyond its threshold. Litestream and hourly catalog backups have different
recovery points. Writer accounts still require retention rights; protect backup
server administration and separately retained server recovery points.

This was a repository security review, not a penetration test of a running
Hostinger installation. Actual SSH isolation, firewall/TLS settings, encrypted
volumes, alert delivery, base-image patching, and replacement-server recovery
still require deployment verification. The branch remains separate from main.

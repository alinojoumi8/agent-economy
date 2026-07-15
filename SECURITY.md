# Security policy

## Supported surfaces

Local mode remains a single-operator research observatory with no
authentication, authorization, tenant isolation, or CSRF protection. Bind
`run.py --serve` and the Vite development server to `127.0.0.1`; never expose
either directly to an untrusted network.

R22 adds a separately enabled hosted service. Its security boundary is:

- invitation-only registration with scrypt password hashes and opaque 256-bit
  session/invitation tokens stored only as hashes;
- tenant memberships with read-only `observer` and controlling `admin` roles;
- PostgreSQL row-level security enabled and forced on tenant-bearing tables,
  with separate web and supervisor roles provisioned `NOSUPERUSER NOBYPASSRLS`,
  default-deny access outside a transaction-scoped tenant context, and run
  discovery granted only to the supervisor role;
- secure same-site `__Host-ae_session` cookies, CSRF checks on mutations,
  authentication throttling, cross-tenant 404 responses, redacted audit events,
  and restrictive HTTP security headers;
- one schema-v11 SQLite world per run, one active writer lease per run, and
  immutable checksummed local/S3-compatible snapshots;
- a non-root read-only application container behind Caddy TLS, with PostgreSQL,
  MinIO, and Prometheus on an internal network.
- a MinIO root identity restricted to bootstrap and a separate bucket/prefix-
  scoped runtime identity that can write/read snapshots but cannot delete them.

The local and hosted servers are distinct entry points. Hosted mode does not
turn the unauthenticated local API into an internet-safe service.

## Hosted threat model and operator obligations

The implemented boundary addresses ordinary cross-tenant reads/writes, stolen
CSRF-free browser requests, credential guessing, duplicate run writers,
path traversal, mutable snapshot replacement, and secret leakage through error
or audit payloads. It assumes the host, PostgreSQL administrator, object-store
administrator, deployment environment, and TLS termination are trusted.

Before any public deployment:

- use a managed secret store or protected environment injection and rotate all
  bootstrap/database/object-store credentials;
- for an existing reference PostgreSQL volume, use the profile-gated
  `rotate-database-passwords` job in the operator runbook; editing `.env` alone
  does not alter stored role passwords;
- keep the migration DSN out of the application container at runtime and verify
  the application login is not superuser and cannot bypass RLS;
- terminate TLS at Caddy or an equivalent trusted proxy, set the exact public
  base URL, restrict database/object-store ports to the private network, and
  configure durable encrypted volumes plus retention;
- exercise snapshot verification and restore, review audit retention and access,
  set external rate limits/alerting, and record a multi-user load/isolation test;
- patch base images and dependencies, rerun secrets/dependency/license scans,
  and complete the hosted acceptance/CI gate.

The repository supplies a reference Compose deployment, not a claim of public
production certification or protection against a malicious infrastructure
administrator.

The hosted load probe accepts credentials only through environment-variable
names in repeated `--user TENANT_UUID,EMAIL,PASSWORD_ENV[,RUN_UUID]` arguments.
Use scoped test identities, remove those environment variables immediately
afterward, and protect the receipt as operational evidence. The emitted JSON is
designed to exclude passwords, cookies, email addresses, response bodies, and
provider data. HTTPS is mandatory. `--allow-insecure-loopback` may be used only
for local HTTPS smoke with a development certificate; never use it against a
remote host or as a reason to expose the local unauthenticated server.

## Secrets and sensitive artifacts

- Put provider credentials only in the ignored `.env` file or process
  environment.
- Never add keys to YAML profiles, reports, screenshots, issues, or pull
  requests.
- Treat run databases as potentially sensitive: they can contain prompts,
  model responses, personas, memories, conversations, and decision evidence.
- Operational logging redacts credential-shaped fields, but review artifacts
  before sharing them outside the project.
- Revoke a provider key immediately if it is exposed and remove it from Git
  history rather than only deleting it in a later commit.

## Reporting a vulnerability

Report security issues privately to the repository owner through GitHub's
private vulnerability reporting if enabled, or another private channel. Include
reproduction steps, affected commit/profile, impact, and a suggested mitigation.
Do not publish credentials or sensitive run contents in a public issue.

For hosted incidents, revoke the affected session/invitation records, preserve
the redacted audit trail and immutable snapshots, rotate relevant credentials,
and verify tenant scope before restoring service. Never copy a tenant's world
database, prompt corpus, or audit evidence into a public issue.

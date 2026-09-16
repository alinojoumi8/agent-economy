# Consolidated release candidate and staging handoff

This work combines the current runtime, storage/recovery branch, Passport/UI
integration, and ECC live-validation fixes into one candidate. It preserves
phase resume, completion guards, read-only replay transactions, bounded export
batches, and terminal hosted-run state while adding recovery admission and
retention. Agent suspension, like revocation, remains possible when storage
admission is closed; reactivation remains blocked.

## Candidate verification

Freeze a clean commit after integration fixes. Run the nine maintained commands
in [reproducibility-v1](../reproducibility-release-profile.md), preserving the
candidate commit/tree and hashed command logs under ignored `reports/out/`.
Run the full CI matrix and hosted PostgreSQL/S3 and SFTP integration jobs on the
same candidate. Existing branch receipts are historical evidence only.

## Staging prerequisites

- Named staging VPS/SSH alias, exact HTTPS origin, and DNS control.
- An isolated stack and data volumes, with no production data or credentials.
- Operator-managed secrets supplied through an ignored environment file; use
  the blank deployment templates and never put values in this document.
- Select the reference S3-compatible stack or the Hostinger/SFTP recovery stack
  explicitly. The latter additionally needs three least-privileged SFTP
  identities and verified server host keys.
- Keep one writer per world. Start with a paused `world-os-external` world,
  bounded connection quotas, and the provider-free server-owned profile.
- Verify real TLS, readiness, login, invitations, isolation, restart, snapshot,
  restore, and monitoring with the actual candidate image digest.

The [operator runbook](../operator-runbook.md) contains reference-stack commands;
[Hostinger deployment](../hostinger-vps.md) describes the recovery stack. A
Compose syntax check or CI database test does not establish a hosted staging
environment.

## External client execution

The [acceptance checklist](../world-os/EXTERNAL-AGENT-ACCEPTANCE.md) remains
authoritative. Independent MCP, Hermes, OpenClaw, Python, and TypeScript each
need their actual native client result against the same hosted candidate.
Hermes/OpenClaw must finish three wakes and read executed receipts. Verify
post-revocation 401 and cross-tenant 403/404 for each applicable result.

Finalize native evidence with `scripts/run_external_connector_acceptance.py`,
using a protected credential file and an independent verifier distinct from
the server operator. Do not invent verifier identities or turn urllib/mock
rehearsals into independent evidence. Record the hosted origin, client versions,
candidate commit/tree, image digest, test tenant, and hashes without secrets.

These three workstreams do not waive the other `production-v1` gates or
authorize a public production launch. The final staged environment and native
connector results must be recorded separately from this preparation document.

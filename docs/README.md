# Agent Economy handbook

The root [README](../README.md) is the friendly project entry point. This
handbook separates user, operator, researcher, developer, and audit material so
each audience can find the authoritative level of detail.

## Learn and run

- [Getting started](getting-started.md) — install, first offline run, experiment,
  optional live routes, resume, replay, and verification.
- [Research guide and use cases](research-guide.md) — causal model, experiment
  discipline, metrics, Oracle evidence, and interpretation limits.
- [Configuration and providers](configuration.md) — profiles, inheritance,
  information boundaries, beliefs, routing, budget, and shock targeting.
- [Local and hosted API reference](api-reference.md) — REST, WebSocket,
  tenant/auth/run routes, request shapes, and PowerShell examples.

## Operate and recover

- [Operator runbook](operator-runbook.md) — safe startup, hosted deployment,
  backup/restore, bounded pilot, production acceptance, phase-aware resume,
  reports, replay, and retention.
- [Troubleshooting](troubleshooting.md) — provider cooldowns, orphaned state,
  legacy databases, dashboard performance, evidence failures, and replay.
- [Security policy](../SECURITY.md) — local/hosted boundaries, RLS/auth threat
  model, credentials, run-data sensitivity, and vulnerability reporting.

## Build and understand

- [Architecture](architecture.md) — deterministic ownership, tick phases,
  packages, information model, persistence, and runtime boundaries.
- [Development and testing](development.md) — setup, test layers, safe behavior
  changes, compatibility, logs, and CI.
- [Contributing](../CONTRIBUTING.md) — contributor contract and PR evidence.
- [Technical specification](../TECH-SPEC.md) — normative implementation design.

## Product and evidence

- [Product requirements](../PRD.md)
- [Delivery tasks](../TASKS.md)
- [Implementation status](implementation-status.md) and
  [printable status](implementation-status.html)
- [Emergent phenomena](emergent-phenomena.md)
- [Live provider validation](live-provider-validation.md)
- [Diagnostic live run `f7c6238bf5`](live-run-f7c6238bf5.md)
- [Closed PR #10 reconciliation](pr-10-reconciliation.md)

## World OS expansion

These documents define the implemented semantics-8 communications lake, the
semantics-9 External Agent Gateway, semantics-10 Agent Commons, semantics-11
compute economy, and semantics-12 civic permit vertical. They extend the root
PRD and technical
specification; historical release contracts remain frozen.

The World OS `PRD.md` and `TECH-SPEC.md` are **successor specifications, not
copies** of the same-named files at the repository root. They differ on purpose:
the root pair is authoritative for current behaviour, this pair for intended
direction. Do not reconcile them into one file.

- [World OS specification index](world-os/README.md) — start here
- [World OS product requirements](world-os/PRD.md)
- [World OS technical specification](world-os/TECH-SPEC.md)
- [Semantics-11 cognition and provider pools](semantics11-cognition.md)
- [Semantics-12 civic city and permit workflow](semantics12-civic-city.md)
- [Framework research and build-versus-buy decision](world-os/FRAMEWORK-RESEARCH.md)
- [External Agent Gateway contract](world-os/EXTERNAL-AGENT-GATEWAY.md)
- [Requirements and disposition matrix](world-os/REQUIREMENTS-MATRIX.md)
- [External-agent threat model](world-os/EXTERNAL-AGENT-THREAT-MODEL.md)
- [External-agent acceptance checklist](world-os/EXTERNAL-AGENT-ACCEPTANCE.md)
- [POLIS cost-chart assumptions](world-os/COST-ASSUMPTIONS.md)
- [Archived POLIS source manifest](world-os/source/polis/SHA256SUMS)
- [Frozen first-lake 30-tick research protocol](world-os/30-TICK-RESEARCH-PROTOCOL.md)
- [Frozen protocol approval manifest](world-os/protocol-manifest.json)
- [Communications and Causal Observatory implementation plan](plans/2026-07-18-world-os-communications-causal-observatory.md)

Connector assets live in the [Python and TypeScript clients](../clients/README.md),
the [portable connection skill](../integrations/connect-agent-economy/SKILL.md),
the Hermes and OpenClaw presets under `integrations/`, and the generated
[OpenAPI contract](../openapi/agent-economy-v2.json).

Generated run reports and acceptance receipts live under `reports/out/`. They
are run-specific evidence, not maintained documentation. The PRD and technical
specification outrank generated narratives when a conflict exists.

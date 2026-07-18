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

## Approved World OS expansion

These documents specify the approved next-generation direction. They do not replace the
root PRD or technical specification until the implementation and release gates are complete.

- [World OS product requirements](world-os/PRD.md)
- [World OS technical specification](world-os/TECH-SPEC.md)
- [Framework research and build-versus-buy decision](world-os/FRAMEWORK-RESEARCH.md)
- [Frozen first-lake 30-tick research protocol](world-os/30-TICK-RESEARCH-PROTOCOL.md)
- [Frozen protocol approval manifest](world-os/protocol-manifest.json)
- [Communications and Causal Observatory implementation plan](plans/2026-07-18-world-os-communications-causal-observatory.md)

Generated run reports and acceptance receipts live under `reports/out/`. They
are run-specific evidence, not maintained documentation. The PRD and technical
specification outrank generated narratives when a conflict exists.

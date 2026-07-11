# Agent Economy documentation

This directory is the operational and engineering handbook for Agent Economy.
The root [README](../README.md) is the short entry point; these guides contain
the details needed to run, inspect, develop, and recover the application.

## Start here

- [Getting started](getting-started.md) — install, run offline, run with MiniMax,
  stop, resume, and generate a report.
- [Operator runbook](operator-runbook.md) — controls, checkpoints, replay,
  experiments, acceptance campaigns, backups, and recovery.
- [Configuration and providers](configuration.md) — YAML inheritance, supported
  profiles, environment variables, budgets, routing, and safety boundaries.
- [Troubleshooting](troubleshooting.md) — startup, provider, run-state,
  dashboard, replay, and CI failures.

## Understand and extend the system

- [Architecture](architecture.md) — components, tick lifecycle, agent population,
  memory, data ownership, determinism, and failure boundaries.
- [API reference](api-reference.md) — REST and WebSocket interfaces used by the
  dashboard and external observers.
- [Development and testing](development.md) — backend/frontend workflow, test
  layers, CI matrix, and change checklist.
- [Documentation maintenance loop](documentation-loop.md) — the bounded docs
  sweep adapted from the published Loop Library workflow.

## Product and evidence

- [Product requirements](../PRD.md)
- [Technical specification](../TECH-SPEC.md)
- [Implementation status](implementation-status.md) and
  [printable report](implementation-status.html)
- [Live provider validation](live-provider-validation.md)
- [Emergent phenomena](emergent-phenomena.md)
- [Rumor experiment](experiments/rumor-vs-control.md)

Generated run reports live in `reports/out/` and are intentionally separate
from maintained documentation.

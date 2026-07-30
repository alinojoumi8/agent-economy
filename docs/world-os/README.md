# World OS specification set

**This directory is not a duplicate of the root specs.** It is the *successor*
specification: World OS is defined as "an extension of the current Agent Economy
process, not a replacement runtime". The root documents describe what is built
and maintained; these describe where that runtime is going, and parts of them
are deliberately ahead of the code.

Anyone comparing `PRD.md` / `TECH-SPEC.md` at the repository root against the
files here will find real differences. Those differences are intentional — do
not "reconcile" the two sets into one file.

## Which document is authoritative

| Question | Authoritative source |
|---|---|
| What does the runtime do **today**? | [root PRD](../../PRD.md) · [root TECH-SPEC](../../TECH-SPEC.md) |
| What is the runtime **becoming**? | [World OS PRD](PRD.md) · [World OS TECH-SPEC](TECH-SPEC.md) |
| What is implemented, released, or rollout-gated **now**? | [maintained implementation-status ledger](../implementation-status.md) |
| What did a dated release gate prove? | [Semantics 8 historical release receipt](SEMANTICS-8-RELEASE-STATUS.md) · [requirements traceability matrix](REQUIREMENTS-MATRIX.md) |

The root PRD tracks the maintained implementation contract through R22. The
World OS specifications extend through Semantics 12. Current status is not
inferred from specification prose: Semantics 8 is the released deterministic
causal baseline; Semantics 9–10 code is rollout-gated; Semantics 11–12 are
implemented opt-in contracts whose public use inherits those hosted gates.
The maintained implementation-status ledger owns those labels.

## Contents

**Product and architecture**

- [PRD.md](PRD.md) — World OS product requirements: target world model,
  communications and Causal Observatory lake, release sequence, open questions.
- [TECH-SPEC.md](TECH-SPEC.md) — normative design for the extension: semantics
  versioning, lakes, and the kernel topology it inherits.
- [FRAMEWORK-RESEARCH.md](FRAMEWORK-RESEARCH.md) — the build-versus-buy decision
  behind the Semantics 8 architecture.
- [REQUIREMENTS-MATRIX.md](REQUIREMENTS-MATRIX.md) — requirement-to-evidence
  traceability; current release labels defer to the implementation-status
  ledger.

**External agent gateway**

- [EXTERNAL-AGENT-GATEWAY.md](EXTERNAL-AGENT-GATEWAY.md) — how outside agents
  (MCP clients, `/api/v2/agent/*`) connect.
- [EXTERNAL-AGENT-THREAT-MODEL.md](EXTERNAL-AGENT-THREAT-MODEL.md) — required
  release-gate artifact for Semantics 9 / schema 13.
- [EXTERNAL-AGENT-ACCEPTANCE.md](EXTERNAL-AGENT-ACCEPTANCE.md) — acceptance
  checklist; live connector rows are deployment gates and must not be marked
  complete from a mock client.

**Research and release evidence**

- [30-TICK-RESEARCH-PROTOCOL.md](30-TICK-RESEARCH-PROTOCOL.md) — the frozen
  causal research protocol `world-os-v8-supplier-warning-v1`.
- [SEMANTICS-8-RELEASE-STATUS.md](SEMANTICS-8-RELEASE-STATUS.md) — historical
  deterministic-readiness and provider-smoke receipt for Semantics 8.
- [COST-ASSUMPTIONS.md](COST-ASSUMPTIONS.md) — assumptions behind the archived
  POLIS cost chart.

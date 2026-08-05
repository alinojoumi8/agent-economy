# Release Evidence and Public Readiness Design

## Goal

Turn the remaining external, live-provider, experiment, long-horizon, and provenance gates into a fail-closed release-evidence campaign. The campaign must distinguish code completion from operational proof and must never convert local mocks, partial runs, or paid preflights into a public-readiness claim.

## Remaining gates

The maintained implementation ledger identifies these unresolved boundaries:

- independent MCP conformance;
- hosted Hermes, OpenClaw, Python, and TypeScript connector receipts;
- Semantics 10 frozen multi-arm experiment, hosted UI, and hosted operational evidence;
- ten fresh V9 MiniMax Oracle arms and their aggregate receipt;
- capped 30-day live rumor pilot;
- explicitly authorized 365-day production acceptance with the governed efficiency boundary;
- final provenance, license, dependency, secret, deployment, backup/restore, and artifact audit.

Existing one-tick or five-tick MiniMax smokes prove routing only. Scripted rehearsals prove mechanics only. Neither substitutes for these gates.

## Considered approaches

### 1. Versioned manifest plus independent gate receipts and a fail-closed collector — selected

Each gate emits a signed or hashed receipt with its own eligibility rules. A release manifest references immutable artifacts and a collector validates them without rerunning paid work. This makes partial progress visible while preventing cross-gate substitution.

### 2. One shell script that runs every gate

External clients, hosted infrastructure, paid campaigns, and long-duration runs have different authorization and retry boundaries. One script would be fragile, unsafe, and difficult to resume or audit.

### 3. Narrative release checklist only

Human-readable notes are useful for review but cannot prove artifact identity, exact commands, configuration, or fail-closed completeness.

## Evidence model

Every gate record has two independent classifications:

- `execution_scope`: `local`, `live_provider`, or `independent_external`;
- `status`: `passed`, `failed`, `blocked`, or `not_run`.

Each record includes gate ID and schema version, commit and tree, UTC start/end, exact sanitized command, configuration digest, environment identity, result summary, artifact paths and SHA-256 hashes, verifier version, and reviewer notes. `blocked` identifies an external condition and cannot be counted as passed. Missing required artifacts, failed commands, hash mismatches, or unknown schema versions fail closed.

No evidence file stores credentials, cookies, OAuth codes, authorization headers, private message bodies, private reasoning, provider raw secrets, or unrestricted environment dumps.

## Collector architecture

A repository-owned release-evidence collector loads a candidate manifest, resolves only repository-relative or explicitly allowed artifact paths, verifies hashes, dispatches gate-specific validators, and emits canonical JSON plus reviewer-readable Markdown. The JSON is the authoritative machine result; Markdown is a deterministic rendering of it.

The collector does not call providers, deploy infrastructure, or mutate runs. Campaign runners and external harnesses produce receipts separately. This separation allows receipt validation to be repeated offline and prevents a reporting command from incurring spend.

## Gate contracts

### External connectors

Independent MCP validates OAuth discovery and protected-resource behavior against a hosted test tenant. Hermes and OpenClaw each complete three wakes, submit authorized work, and read executed receipts. Generic Python and TypeScript clients complete equivalent REST flows. Receipts include client version, tenant/run scope, public request/response hashes, revocation/isolation results, and independent signer identity. Local mock clients cannot satisfy these records.

### Semantics 10 rollout

The frozen experiment records all arms, commitment, feed/post/explicit-read exposure, moderation behavior, hosted browser evidence, operational health, exact replay, and contamination exclusions. Every arm must be present; an excluded or substituted arm fails the aggregate gate.

### V9 Oracle campaign

Seeds 7381–7390 use the committed V9 profiles and commitment. Only the Oracle uses the exact MiniMax-M3 route and pinned pricing/cache policy. All ten source runs must be eligible, resolve 60 forecasts across both outcomes, satisfy p90 and Brier thresholds, and produce exact one-time offline replays with no fallback or live dispatch. No V1–V8 artifact enters V9.

### Rumor pilot

The capped 30-day profile runs only after explicit live-inference and spend approval. It must pass provider preflight, bounded cost, scheduled prediction, rumor exposure/trust/outflow evidence, reconciliation, provenance, integrity, and exact replay. Failure changes status to `failed`; it does not authorize the 365-day run.

### Production acceptance

The 365-day run begins only after pilot approval and a clean release-candidate commit/tree. It requires the configured population, shocks, Oracle samples, emergent-phenomena evidence, real provider provenance, spend/efficiency checks, terminal completion, database integrity, balanced ledgers, checkpoints, report/receipt hashes, and exact replay.

### Final audit and deployment

The exact candidate repeats license, dependency, secret, provenance, dataset, build reproducibility, hosted backup/restore, tenant isolation, load, and deployment checks. Public deployment receives a separately authorized receipt. A Git tag or publication is prohibited until the collector validates every required gate as passed.

## Authorization and cost control

Local collector and rehearsal work may run without paid-provider approval. Any live-provider, hosted external-client, deployment, or uncapped campaign task stops at a documented authorization checkpoint stating profile, model, maximum or expected spend, infrastructure target, and retention. Approval for one gate never authorizes the next.

## Failure and resume behavior

Receipts are append-only and content-addressed. Failed or partial source artifacts are retained as diagnostic evidence and never rewritten into eligibility. Resume is allowed only when the gate contract and run claim permit it; otherwise a fresh identity is required. The collector reports every missing or blocked gate rather than stopping after the first, but its overall result remains failed until all required records pass.

## Verification

- Manifest-schema and canonical-rendering tests.
- Mutation tests for missing files, hash changes, duplicate gates, secret canaries, invalid scope/status, and false substitutions.
- Offline validation of representative local, live, blocked, failed, and not-run receipts.
- Focused tests for each existing Oracle and acceptance validator.
- Independent external receipt verification without credentials.
- Final full Python/dashboard/hosted gates on the exact candidate.

## Acceptance evidence

Completion requires a versioned candidate manifest, verified immutable gate receipts, deterministic JSON/Markdown collector output, zero secret canaries, and an overall passed result on the exact published commit/tree. Producing the task tooling alone is implementation progress, not release readiness; every external and live gate must also hold qualifying evidence.

## Out of scope

- Automatically purchasing provider capacity or deploying without authorization.
- Reusing archived Oracle campaigns as V9 evidence.
- Treating local mocks as independent external receipts.
- Deleting failed or diagnostic run artifacts as part of report generation.

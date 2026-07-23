# Agent Economy

[![CI](https://github.com/alinojoumi8/agent-economy/actions/workflows/ci.yml/badge.svg)](https://github.com/alinojoumi8/agent-economy/actions/workflows/ci.yml)

**A living miniature economy for studying how information changes beliefs,
decisions, institutions, and markets.**

Agent Economy runs a US-style world populated by persona-driven citizens,
founders, bankers, journalists, public officials, and an economic Oracle. Agents
can work, buy goods, borrow, lend, trade, publish, gossip, form companies, vote,
become ill, and panic. LLMs propose decisions; a deterministic engine validates
and settles every consequence through an exactly balanced double-entry ledger.

> Agent Economy is a research simulator, not a real-economy forecast or
> financial advice. The default desktop profile uses live, evolving agents;
> `runs/base.yaml` remains the explicit free deterministic profile.

The default desktop launch is the Semantics-11 cognition economy:

```powershell
# .env must provide DEEPSEEK_API_KEY, MINIMAX_API_KEY, and KIMI_API_KEY.
# Ollama must serve the bounded-context alias created below.
ollama pull qwen3.5:9b
ollama create agent-economy-qwen3.5:9b-16k -f deploy/ollama/Modelfile.qwen3.5-9b-16k
python run.py --preflight-live --serve --approve-live-inference
```

It runs independent Ollama, DeepSeek, MiniMax, and Kimi pools, assigns citizen
compute subscriptions, and persists learnable domain skills. See the
[Semantics-11 live cognition guide](docs/semantics11-cognition.md).

## Legal-Political Economy v2

The flagship `runs/v2.yaml` world makes institutions part of the economy rather
than background flavor:

- Executed contracts compile into enforceable obligations; claims, evidence,
  settlements, judgments, injunctions, cap tables, and ledgers share one action path.
- Startups move through formation, typed VC rounds, IP, disclosures, trading,
  merger review, remedies, litigation, and exit.
- Claims and articles spread through recorded asymmetric exposures before they
  can affect beliefs, trades, investments, or votes.
- A two-party legislature, elections, lobbying, agencies, and typed policy rules
  create endogenous economic-political feedback.
- 1,000 agents inhabit Northstar, Ironvale, and Suncoast. One hundred strategic
  agents may use an LLM; 900 peripheral agents take scheduled, local
  state-derived policy turns without creating model-call records.
- Multicurrency ledgers, inventory-backed FX books, cross-border contracts,
  trade, migration, and regional specialization remain exactly replayable.
- Maintained profiles run engine semantics 7: defaults recognize only net bank
  losses after collateral, retirees can draw their own savings, arrivals receive
  governed persona enrichment, and qualified trade and migration opportunities
  become autonomous actions. Peripheral policy turns, actor-created first stock
  prices, the state-qualified startup funding chain, local-currency action
  filtering, and unique-worker unemployment keep the observatory economically
  active without weakening replay. Stored semantics 1–6 retain their original rules.
- The observatory adds a living economic map, legal/political/startup surfaces,
  causal traces, God-mode actions through the normal validator, and static replay export.
- Pinned dataset manifests and paired-seed scenario packs support model-conditional
  counterfactual research without presenting the simulation as a forecast.

```powershell
# Free 1,000-agent flagship run
python run.py --config runs/v2.yaml --ticks 30

# Verify pinned data without network access
python run.py --verify-datasets config/data-manifest.yaml

# Explicit networked refresh (never runs implicitly)
python run.py --refresh-datasets config/data-manifest.yaml

# Paired policy lab; defaults to 20 seeds
python run.py --counterfactual scenarios/ai-competition-merger.yaml

# Self-contained replay artifact
python run.py --export-static RUN_ID --output static_exports/demo.html
```

See [the v2 architecture and research guide](docs/v2-guide.md) for schemas,
legal-model limits, provenance, scenario authoring, replay guarantees, and the
validity boundary.

## Why this project exists

Many multi-agent demos make interesting text but cannot explain where money
came from, reproduce a run, or separate a model's belief from a scripted engine
effect. Agent Economy is built around the opposite priorities:

- **Mechanically valid**: every dollar is conserved; markets, loans, payroll,
  taxes, insurance, and failures use deterministic rules.
- **Causally inspectable**: information exposure, belief change, proposed
  decision, validated action, and economic effect are persisted separately.
- **Reproducible**: seeded offline runs produce stable evidence; exact replay
  rebuilds a source run without contacting a provider.
- **Observable**: a local React dashboard shows the economy, agents, institutions,
  news, conversations, forecasts, costs, shocks, and acceptance gates live.
- **Provider-aware**: real-model profiles preflight routes, meter cost, survive
  rate limits, and pause visibly instead of silently changing models.

## What can you use it for?

| Use case | Example question |
|---|---|
| Misinformation research | Can a false bank rumor reduce trust and cause deposit flight? |
| Monetary policy | How does a rate shock move loan quotes, hiring, output, and markets? |
| Agent comparison | Do different model/provider mixes behave differently under identical mechanics? |
| Forecast calibration | Is the read-only Oracle well calibrated after predictions resolve? |
| Economics and AI education | How do beliefs become actions without violating accounting constraints? |
| Multi-agent systems engineering | Can a long, costly run be resumed, replayed, audited, and budgeted? |

## How it works

```mermaid
flowchart LR
    INFO[News, rumors, conversations] --> CONTEXT[Role-scoped agent context]
    CONTEXT --> MODEL[Scripted policy or LLM]
    MODEL --> PROPOSAL[Structured decision and belief updates]
    PROPOSAL --> VALIDATE[Deterministic validation]
    VALIDATE --> ECON[Ledger, banks, firms, labor, market]
    ECON --> METRICS[Metrics and events]
    METRICS --> UI[Observatory, reports, replay]
    METRICS --> INFO
```

One tick is one simulated day. Nightly mechanics settle obligations and shocks;
agents then perceive, decide, trade, publish, converse, update memory, and
finalize a reconciled day. Maintained semantics-7 profiles preserve the
research-valid information boundary while adding net loan charge-offs,
retirement liquidity, deterministic arrivals, governed arrival personas, and
autonomous regional trade/migration. Stored semantics 1–6 runs are never
silently upgraded, and a markerless stored semantics-7 source keeps its
historical citizen-tier assignment.

## Five-minute offline start

Requirements: Python 3.11 or 3.12. Node.js is not needed unless you change the
dashboard.

```powershell
git clone https://github.com/alinojoumi8/agent-economy.git
Set-Location agent-economy
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements.lock

# Free, deterministic, no API key
python run.py --config runs/base.yaml
```

Open <http://127.0.0.1:8000>. The world starts paused; press **Run** or **Step**.

To play one citizen through the same validator and ledger used by autonomous
agents, start the provider-free participant sandbox instead:

```powershell
python run.py --config runs/participant.yaml
```

Open a living citizen in the observatory, choose **Take control**, queue one
action, and press **Step**. The citizen inspector retains a paginated audit of
queued, executed, rejected, and cancelled commands. Participant runs are clearly
marked and cannot be used as acceptance evidence.

macOS/Linux users can activate with `source .venv/bin/activate`. A headless smoke
run that writes a standalone report is:

```bash
python run.py --config runs/base.yaml --ticks 3
```

> **Important:** `python run.py` without `--config` selects the live production
> profile. Use the explicit `runs/base.yaml` command for offline work.

## A first experiment

Run five treatment seeds and five same-seed controls for the rumor scenario:

```powershell
python run.py --experiment runs/experiments/rumor_vs_control.yaml
```

Artifacts are written to `reports/out/` in JSON, Markdown, and HTML. Treatment
and control worlds are isolated and every arm is reconciled.

The rumor engine only adds an observation. It does **not** lower trust or move
money. The causal path must be produced by agents:

```text
exposure -> belief update -> decision -> deposit transfer -> reserve pressure
```

The evaluator measures trust relative to each exposed agent's real pre-rumor
baseline and fails closed when history is missing.

## What is in the observatory?

- **Run controls**: run, pause, step, speed, safe stop/report, phase-aware resume.
- **Macro view**: daily and rolling final-goods output, labor income, CPI,
  correctly windowed inflation, unemployment, money, inequality, and markets.
- **Agent inspector**: persona, accounts, loans, holdings, memories, bounded
  beliefs, provenance, prompts, model responses, and decision audit.
- **Institutions**: bank balance sheets, firms, government, VC, healthcare,
  newsroom, and exchange.
- **Information flow**: articles, conversations, shocks, and high-importance
  events.
- **Oracle**: evidence-bounded probability forecasts, automatic resolution,
  Brier scores, and run/pooled calibration.
- **Acceptance**: completed gates, actual/projected spend, Oracle sample count,
  shock traces, and rumor-window evidence.
- **Participant sandbox**: take control of one citizen, queue one validated
  action per day, and inspect the durable execution result.
- **Replay and export**: tick-by-tick historical viewer plus standalone reports.

## Run profiles

| Profile | Agents/purpose | Provider policy |
|---|---|---|
| `runs/evolving-live.yaml` | Default 100-agent Semantics-11 cognition world | Ollama 2, Ollama Cloud 3, DeepSeek 6, MiniMax 2, Kimi 2; global 10; resource guard and strict live preflight |
| `runs/base.yaml` | Fast local world | Scripted, free, deterministic |
| `runs/participant.yaml` | One-citizen participant sandbox | Scripted, free, step-only |
| `runs/production.yaml` | Approx. 100-agent live world | MiniMax citizens/founders; Kimi institutions/Oracle |
| `runs/v2-spec-closure-rehearsal.yaml` | Five-tick semantics-7 closure fixture | Scripted, free, deterministic |
| `runs/v2-spec-closure-live.yaml` | Five-tick bounded semantics-7 pilot | MiniMax persona/strategic roles; scripted background; $1 cap |
| `runs/r21-real-us.yaml` | SCF/SUSB calibrated fictional genesis | Scripted, free, deterministic |
| `runs/acceptance/rehearsal.yaml` | Full acceptance mechanics | Scripted, free |
| `runs/acceptance/pilot.yaml` | 30-day rumor pilot | Live, explicit approval, $25 cap |
| `runs/acceptance/production.yaml` | 365-day release evidence | Live, explicit approval, $200 efficiency gate |
| `runs/oracle/calibration-control-rehearsal.yaml`, `calibration-rehearsal.yaml` | 335-tick control/treatment Oracle schedule rehearsals | Scripted, free, ineligible for live receipt |
| `runs/oracle/v9-seed-7381-control.yaml` ... `v9-seed-7390-rumor.yaml` | Current pending v9 10-run/60-forecast calibration corpus | Scripted world; live `MiniMax-M3` Oracle only through the exact `openai_compat` adapter; automatic cache accounting; governed answer repair; scheduled-latency call floor; shared state-aware preflight; occurrence-aware replay citations; $25/run cap; no v9 live evidence claimed yet |

Production never silently falls back when a key, route, or provider fails.
Provider configs select `prompt_cache_mode` from `off`,
`provider_automatic`, `openai_key`, or `anthropic_ephemeral`; the legacy
`prompt_cache_key` option remains an alias for OpenAI-compatible keyed caching.

## Optional real-model setup

```powershell
Copy-Item .env.example .env
# Add DEEPSEEK_API_KEY, MINIMAX_API_KEY, and KIMI_API_KEY locally; never commit .env.
# Create the app-specific 16K-context alias and keep Ollama running.
ollama pull qwen3.5:9b
ollama create agent-economy-qwen3.5:9b-16k -f deploy/ollama/Modelfile.qwen3.5-9b-16k

python run.py --config runs/evolving-live.yaml --preflight
python run.py --config runs/evolving-live.yaml --preflight-live
python run.py --config runs/evolving-live.yaml --serve --approve-live-inference
```

Static preflight validates configuration. Live preflight also sends one small
real JSON-contract completion through every routed provider. Any inference run
requires the explicit `--approve-live-inference` flag. Read the
[operator runbook](docs/operator-runbook.md) before starting it.

## Resume, replay, and reports

```powershell
python run.py --config runs/base.yaml --resume <RUN_ID>
python run.py --replay <RUN_ID>
python run.py --report <RUN_ID>
```

- **Resume** restores the stored phase cursor and reuses completed calls.
- **Replay** opens the recorded source read-only, creates a new database, uses
  stored LLM responses only, reconstructs persisted acceptance-checkpoint
  effects, and prints canonical table-hash equality proof.
- **Report** regenerates HTML/Markdown from a stored database.

Each run is a portable SQLite file under `data/runs/`. It contains the economic
state and the scientific audit trail: events, beliefs, memories, conversations,
predictions, metrics, shocks, ledger entries, and model-call evidence.

CI also restores the sanitized portable fixture for live run `fd0adc5dc1` and
replays its ten recorded ticks with networking disabled. The source database is
stored as semantics 5—not semantics 6—so the fixture preserves that historical
contract while canonicalizing physical LLM row IDs through logical call content.
Fixture format v2 strips raw provider envelopes, retains only the public text
and cached-token counter, converts repository paths to `repo://`, and restores
the source's recorded dataset/calibration/scenario rows rather than substituting
today's mutable manifests. Its artifact SHA-256 is
`af57eed59e47e9057d7645a65e1bb6f2b579a6a63a377fd6301f33af3955e2d7`; the
normalized reconstructed replay hash is
`2efcabedba51e4bff3ccfd36393db20d13b41cd5d3e9a3772df42015db4f9170`.

## Project structure

```text
run.py             CLI and local application entry point
runs/              offline, production, acceptance, and experiment profiles
config/            dataset manifests and hosted-service configuration
engine/            deterministic ledger and economic mechanics
agents/            personas, role contexts, scheduling, memory, decisions
world/             genesis, phase loop, shocks, metrics, information layer
llm/               adapters, routing, readiness, retry, metering, governor
oracle/            evidence tools, prediction, resolution, calibration
experiments/       treatment/control harness
research/          calibrated initialization, hashes, and research utilities
scenarios/         versioned counterfactual scenario packs
server/            FastAPI, WebSocket, replay API, committed dashboard bundle
hosted/            optional R22 catalog/auth/RLS, supervisor, artifacts, API, CLI
clients/           thin Python and TypeScript external-agent REST clients
integrations/      portable skill plus Hermes, OpenClaw, and generic presets
openapi/           generated external-agent REST/MCP-adjacent contract
deploy/            Compose, Caddy, Prometheus, PostgreSQL role initialization
dashboard/         React/Vite/Tailwind/Recharts source
reports/           run reports and acceptance receipts
tests/             unit, invariant, integration, property, golden, acceptance
docs/              maintained user/operator/research/developer handbook
```

## Optional hosted multi-user mode

R22 adds a separately enabled hosted service while preserving the zero-ops
local workflow above. It provides invite-only tenants and roles, authenticated
shared-run observation/control, a PostgreSQL control plane with forced row-level
security, one deterministic SQLite v11 world per run, immutable local or
S3-compatible snapshots, and a hosted dashboard. The reference deployment in
`deploy/compose.yaml` includes PostgreSQL, MinIO, migrations, the application,
Caddy, and Prometheus. Start with
[configuration](docs/configuration.md), the
[operator runbook](docs/operator-runbook.md), and
[security policy](SECURITY.md); do not expose the local `run.py --serve` app.

### External agents and Agent Commons

World OS semantics 9/schema 13 adds a common external-agent gateway for
Hermes, OpenClaw/Moltbot, custom MCP clients, and generic REST agents. Semantics
10/schema 14 adds Agent Commons with deterministic feeds and explicit-read
information effects. Semantics 11/schema 15 adds citizen compute subscriptions,
authoritative skill progression, provider-pool routing, and operational LLM
attempt evidence. Outside runtimes keep their own models, prompts, memories,
provider credentials, and inference costs; Agent Economy owns only identity,
authorization, deterministic turns, receipts, and world state.

Start from the [gateway contract](docs/world-os/EXTERNAL-AGENT-GATEWAY.md),
[client quickstart](clients/README.md), or
[portable connection skill](integrations/connect-agent-economy/SKILL.md). The
reference local profile is `runs/world-os-external.yaml`. Hosted rollout remains
invite-only until the independent protocol and real-connector gates in the
[acceptance checklist](docs/world-os/EXTERNAL-AGENT-ACCEPTANCE.md) pass.

## Documentation

| If you want to... | Read |
|---|---|
| Install and run the app | [Getting started](docs/getting-started.md) |
| Understand the research model and metrics | [Research guide](docs/research-guide.md) |
| Understand components and data flow | [Architecture](docs/architecture.md) |
| Customize a run or provider | [Configuration](docs/configuration.md) |
| Run evolving live agents and audit cognition | [Semantics-11 cognition](docs/semantics11-cognition.md) |
| Automate the local server | [API reference](docs/api-reference.md) |
| Connect Hermes, OpenClaw, or a custom agent | [External Agent Gateway](docs/world-os/EXTERNAL-AGENT-GATEWAY.md) and [clients](clients/README.md) |
| Operate, pause, resume, or accept a run | [Operator runbook](docs/operator-runbook.md) |
| Diagnose a failure | [Troubleshooting](docs/troubleshooting.md) |
| Develop or contribute | [Development](docs/development.md) and [Contributing](CONTRIBUTING.md) |
| Inspect product commitments | [PRD](PRD.md), [technical spec](TECH-SPEC.md), [status](docs/implementation-status.md) |

The [handbook index](docs/README.md) links all maintained and historical evidence
documents.

## Current status and limits

All PRD-v1 P0/P1 feature surfaces and the R18 participant, R19 1,000-agent,
R20 multi-region, R21 real-U.S. calibration, and R22 hosted multi-user code
surfaces are implemented. The semantics-7 code closure adds
the remaining bank, retirement, arrival/persona, autonomous trade/migration,
portable replay, and cache-policy contracts without changing schema v11.

Current `main` at `c9f0b23` also restores measured economy activity in the
semantics-7 observatory. Scheduled peripheral agents execute deterministic local
policies with zero model-call rows; households form the first stock price from
fundamentals through ordinary bids and asks; qualified partners, founders, and
lawyers advance pitches through term sheet, diligence, round close, and IP;
regional action contexts expose only local-currency opportunities until FX is
performed; and unemployment counts each worker once, including employed founders.

The semantics-7 closure is locally verified. The free run `5a0d40d773` exercised
every target effect through tick 5 at zero spend and replayed exactly with hash
`fa190b0d…e8cffc34`. The live run `b4832032ba` completed five semantics-7 ticks
with 21 MiniMax plus 36 scripted calls, all 42 proposals accepted, `$0.01121124`
spend under the `$1` cap, zero provider/provenance/privacy defects, balanced
currencies, and exact replay hash `ec2b2409…c399ae2`. The focused gate passed 86
tests before the final hardening pass, a 93-test integrated adversarial gate
passed afterward, and the semantics-7 closure suite passed 280 in 165.73
seconds. The post-merge compatibility/replay cleanup gate passes 303 tests in
178.22 seconds.
Dashboard tests, notice validation, audit, two byte-identical
production builds, dependency audit, secret scan, and local hygiene are green.
PR #15 merged to `main` as `255555c2b24530c0bd39aed2f501277a468adc0a`
after its exact-head dashboard plus Ubuntu/Windows Python 3.11/3.12 matrix
passed. Post-merge CI run `29368193807` repeated all five jobs successfully.
Tagging and publication remain separate release decisions.

The final v3 receipt-hardening tree passed 599 Python tests with 8 skipped in
1,618.07 seconds. The preceding replay-integrity revision separately passed 590
with 8 skipped, 23 dashboard tests, a fresh 603-module dashboard build, and
checksum verification for the pinned FRED/BLS/SCF/SUSB datasets. Free production-workflow rehearsal
`881ed41994` completed 365 ticks
with 100 living agents, zero spend, balanced ledger state, zero operational
failures, six completed and resolved Oracle checkpoints, all five shock traces,
the five-seed experiment, and three run-bound reviewed phenomena. Its acceptance
receipt passed 19 of 20 checks; only `real_providers` was false because every
route was intentionally scripted. Companion replay
`replay-881ed41994-3465cb3101` matched tick 365 and hash
`37d18cf45365532b39de68efffac68cacb0010ab453734110b8e057e498786ed`;
all deterministic tables matched and `differences: []`.

The 30-day rumor gate, successful v9 Oracle latency/calibration campaign, and
365-day/$200 acceptance run remain separate and are not replaced by the
five-tick pilot or scripted 365-tick rehearsal. A final provenance, license,
dependency, and secret audit is also required before any public release.

The archived `oracle-calibration-v1-s7301` source completed tick 335 with six
resolved forecasts and valid live-provider provenance, but its offline replay
diverged at the first arrival. The cause was a staged-genesis persona RNG stream
that was not checkpointed/restored; read-only checkpoint inspection also left
SQLite WAL/SHM sidecars. That source is diagnostic evidence only and is not
eligible acceptance evidence. The preceding replay-integrity revision persists
and validates both semantics-7 RNG streams, finalizes standalone checkpoints
without SQLite sidecars, and fails replay when its target tick is not reached.
Its focused, representative aggregate, and full-suite verification passed.

Oracle campaign tooling is implemented. The archived v2 seed-7311 source and
its generated offline replay both reached tick 335 and crossed the first
arrival without the v1 divergence. Canonical verification returned
`exact: true` with `differences: []`; receipt creation then failed because the
checkpoint audit counted all preserved agent rows instead of validating the
bounded living population separately from deceased rows: after one death and
its replacement arrival, the correct census was 101 stored rows, 100 living,
and one deceased. V2 is immutable diagnostic evidence and is never resumed,
rewritten, or reused. The corrected receipt contract validates the
living/deceased census, requires each death, schedule, and arrival to link in
chronological order, authenticates their `NIGHT_CLOSE` phase and agent subject
provenance, consumes every due schedule exactly once, and enforces the fixed
5–20-tick replacement delay. V3 seed 7321 then completed its source and exact
companion replay, but its original receipt admitted only four of six forecasts:
the receipt incorrectly applied accepted-plan validation to authenticated
planner attempts that had been rejected before a valid retry. The original
receipt preserves the pre-inspection source SHA-256. The local source artifact
was later write-opened during diagnosis, so it is excluded diagnostic evidence
and is not admissible in any release manifest.

V4 seeds 7331 and 7332 completed with exact companion replays but remain
diagnostic evidence only. Seed 7333 exposed a governed-tool mismatch: `gov` was
advertised as a ledger target, while execution looked under the wrong account
owner instead of the system-owned treasury account. That state-dependent
failure was mislabeled as a preflight plan rejection, so the receipt correctly
excluded the run. No v4 source, response, claim, initialized marker,
checkpoint, replay, profile, commitment, manifest entry, or seed is reused.

V5 seeds 7341–7347 then produced passed, eligible source receipts with exact
companion replays. Seed 7348 finalized its source, but replay encountered
duplicate same-tick loan-default events with indistinguishable public citation
identities. The two outlets failed closed to daily briefs at ticks 301 and 331
(four articles total), and the changed virality propagated through nine
information tables. Seeds 7349–7350 were never run. The seven receipt-bound
replay databases and fourteen Oracle source/replay receipts belong only to
seeds 7341–7347; seed 7348 has no eligible replay database or Oracle
source/replay receipt. Final corrected offline replay
`replay-oracle-calibration-v5-s7348-5220b912ae` reached tick 335 with
`exact: true`, identical logical hash `fee77b65…b378`, all 82 deterministic
tables exact, and `differences: []`; this post-source fix is diagnostic proof
only and creates no eligible v5 receipt. Completed cleanup removed 320 v5
source-checkpoint database bodies, 160 fixed-code replay checkpoint bodies,
four derived fixed-replay final databases, and the superseded partial seed-7343
replay: 485 database files and `111.945217 GiB` total. Retained artifacts are all
authoritative final sources; the seven eligible replay databases and fourteen
source/replay receipts for seeds 7341–7347; all source-checkpoint
manifests/hashes, claims, and reports; the 160 fixed-code replay checkpoint
manifests; and the ignored compact final exact receipt. Seed 7348 remains
excluded and has no eligible source/replay receipt or retained replay database.
No v5 evidence is pooled into a later release corpus.

V6's first arm, seed 7351, stopped at tick 65 after a successful Kimi response
used `confidence: "medium"` instead of the strict `low|med|high` contract. The
runtime persisted a rule rejection, an `insufficient_data` prediction, and a
missed acceptance checkpoint. The arm spent $0.18351 and recorded no provider,
budget, or tool-execution failure. Preserve v6 as excluded diagnostic evidence;
seeds 7352–7360 were never run, and no v6 artifact may enter a later corpus.

V7 is now archived and excluded. Seeds 7361–7364 produced passed, eligible
source receipts with exact tick-335 companion replays. Seed 7365 remains paused
at tick 335 in `FINALIZE` with 32,114 persisted calls, 12 governed Oracle calls,
six resolved forecasts/checkpoints, balanced USD ledger state, no critical
events, and `$0.2754108` spend. Its authoritative database is 518,561,792 bytes;
SHA-256 is
`b48b0c5a02270f6b09eafb5c32c8480a44f42057289048faedde9474d8ca8ce5`;
immutable SQLite `quick_check` is `ok`, with no WAL/SHM sidecars. The completion
event recorded 13,658 ms while the two governed calls summed to 13,660 ms, so
receipt validation correctly rejected the continuous scheduled-latency floor
before any replay or source receipt was published. This is the continuous scheduled-latency floor defect. Because the source claim is
bound to commit `7642d7a193f8d0806d6043e8b105b6f469f649c8` and tree
`d9e02a64efd555fb6d0a5c1414351a6db238ad62`, seed 7365 is never resumed,
repaired, substituted, or post-fix receipted. The claim SHA-256 is
`705dadfe8e9ed8588d0a4329bf0e681ce2f83e2a531ff40ee94c783d83f1f18e` and the
initialized-marker SHA-256 is
`f07efa9e3ff5452aa4aea6ff560a4974c86c839fac7b9aa9e5c78aeb0f900bfd`.
Seeds 7366–7370 were never run.
There is no V7 aggregate manifest or receipt. The eight source/replay receipt
JSONs for seeds 7361–7364 remain diagnostic only; no V7 response, claim,
initialized marker, checkpoint, replay, receipt, profile, commitment, manifest
entry, run identity, artifact, or seed enters v8.

The producer now clamps both continuous-monotonic and resumed-wall-clock
scheduled latency to at least the conservatively rounded sum of the persisted
governed-call latencies. V8 is archived and excluded: seeds 7371–7374 each
produced passed, eligible source receipts and exact tick-335 companion replays,
while seed 7375 stopped at tick 245 after four of six forecasts when Kimi
returned HTTP 403 for the exhausted billing-cycle quota. The source persisted
one `provider_failure`, spent `$0.19651848`, and remains a healthy standalone
SQLite database. It is not resumed or substituted. The archive retains five
source databases, four replay databases, eight source/replay receipts, and all
checkpoint manifests. After the archive commit became durable, conservative
cleanup removed exactly 189 V8 source-checkpoint database bodies—40 each for
seeds 7371–7374 and 29 for seed 7375—totalling 43,999,223,808 bytes. Retain 189
source checkpoint manifests, 160 replay checkpoint manifests, five claims,
five initialized markers, and every final artifact listed above. The
post-cleanup inventory contains zero source or replay checkpoint bodies and
zero V8 SQLite sidecars. All retained final databases pass immutable read-only
`quick_check`, and eligible source/replay hashes still match their receipts.
No V8 evidence enters a later corpus.

V9 is the current fresh commitment: campaign `oracle-calibration-v9`, version
9, seeds 7381–7390 with odd control and even rumor arms, commitment SHA-256
`8a1845ebe9e916b8618a1c17170dc8a2b439c929ea1e1118670e21683c341a8e`, and
`runs/oracle/manifest-v9.template.yaml`. Only the Oracle is live, using
`MiniMax-M3` through provider kind `openai_compat` at
`https://api.minimax.io/v1`, key environment `MINIMAX_API_KEY`, `/models`
healthcheck, 180-second timeout, `max_tokens_field: max_completion_tokens`,
request defaults `max_completion_tokens: 4096` and `reasoning_split: true`,
and `prompt_cache_mode: provider_automatic`.
The standard MiniMax ≤512k rates are `$0.30/M` input, `$1.20/M` output, and
`$0.06/M` automatic cache reads; every arm retains a `$25` cap. A disposable
one-call MiniMax probe and a deliberately unclaimed five-tick Oracle rehearsal
both succeeded through that exact adapter. They establish operational
readiness only and are not V9 corpus evidence. Passing still requires all ten
fresh exact source/replay pairs, 60 resolved forecasts across both outcomes,
p90 below 60 seconds, and Brier below 0.25. No V9 live evidence is claimed
before the aggregate gate passes. The fresh V9 precommit tree passed all 659
Python tests with 8 environment-gated skips, 23 dashboard tests, the 603-module
production build and static-bundle freshness check, pinned-dataset verification,
dependency checks, and `git diff --check`. See the
[operator runbook](docs/operator-runbook.md).

The completed V7 archive cleanup removed exactly the 200 source checkpoint
database bodies under `data/checkpoints` matching anchored
regex `^oracle-calibration-v7-s736[1-5]_t\d+\.db$`—40 per source. That exact set
is 49,647,239,168 bytes (`46.237595 GiB`).
All 360 source/replay checkpoint manifests and hashes, five final source
databases, four final replay databases, eight source/replay receipt JSON files,
the five existing claim/initialized-marker pairs for seeds 7361–7365, profiles,
commitments, template, base configuration, reports, and the authoritative
seed-7365 database were retained. No broad V7 wildcard was used.

R21 is opt-in through `runs/r21-real-us.yaml`. Its pinned 2022 Federal Reserve
SCF fixture supplies income, liquid-financial-asset, and total-net-worth draws;
`LIQ` funds modeled deposits while `NETWORTH` is retained as an engine-owned
off-ledger calibration baseline. The pinned 2022 Census SUSB fixture supplies
employer-firm headcounts, and exact replay uses recorded targets without
reopening the manifest. Simulated identities remain fictional.

The recorded five-tick R21 gate `24d8dc242e` sampled 70 households and 12
realized firms, retired no under-age SCF category-3 respondent, had zero
reconciliation failures, and replayed offline as
`replay-24d8dc242e-a9ed4f2910` with identical hash
`95b4b8bd…0cee369a`. The integrated Python gate passes 328 tests. R21 merged
through PR #18 at `21bbf30051e3de8c9b5b7a50e48a0e342d94676a` after all five
PR jobs passed. Post-merge main run `29403186283` repeated all five jobs
successfully.

Local mode remains intentionally single-operator and unauthenticated: bind it
to `127.0.0.1` and never expose it directly. R22's optional hosted path adds
authentication, tenant/role isolation, CSRF/throttling/audit, a lease-based
single-writer supervisor, durable snapshots, and deployment assets without
changing engine semantics or schema. Exact local Compose evidence at
`53081f2` passed TLS readiness, tenant isolation, immutable S3 snapshots and
cold restore, atomic database-password rotation, Prometheus scraping, and a
200-request load probe with 80 enforced cross-tenant denials and zero failures.
PR #19 head `1cf1d0a` then passed the six-job dashboard, hosted PostgreSQL/S3,
and Ubuntu/Windows Python 3.11/3.12 matrix in run `29409250171`, and merged as
`1806294d4fecbe13ddbdf615c459755c74293599`. The post-merge push run
`29411023992` was not executed: GitHub rejected every zero-step job because of
the repository account's billing/spending-limit state. That historical runner
block is not a code-test failure; handbook PR #24 subsequently passed the full
six-job matrix. No public production deployment is claimed. The implementation
in PR #20 is authorized for squash merge, while every pending live gate, the
final provenance audit, tagging, publication, and public deployment remain
separate release decisions.

See [SECURITY.md](SECURITY.md) for data/credential boundaries and
[docs/implementation-status.md](docs/implementation-status.md) for the evidence
matrix.

## Licensing and attribution

The project source is licensed under Apache-2.0. Dataset-specific provenance,
terms, and citation guidance are recorded in [NOTICE](NOTICE) and the pinned
[data manifest](config/data-manifest.yaml). The dashboard's complete generated
dependency notices are available in
[dashboard/public/THIRD_PARTY_NOTICES.txt](dashboard/public/THIRD_PARTY_NOTICES.txt)
and are shipped with the server bundle at
[server/static/THIRD_PARTY_NOTICES.txt](server/static/THIRD_PARTY_NOTICES.txt).
Persona-generator provenance and the distinction between upstream inspiration
and locally authored code are documented in
[agents/personas/ATTRIBUTION.md](agents/personas/ATTRIBUTION.md).

## Development

Run the complete hash-locked local gate in
[docs/development.md](docs/development.md#test-layers). It covers compilation,
pinned datasets, Python/dashboard tests, dependency and notice audits, the
production bundle, and diff hygiene.

Dashboard builds write to `server/static/`; that bundle is committed so Python
users receive the full UI without Node.js. Contributions should preserve the
ledger, information-boundary, belief-provenance, determinism, and replay
invariants described in [CONTRIBUTING.md](CONTRIBUTING.md).

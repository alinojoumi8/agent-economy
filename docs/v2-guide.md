# Agent Economy v2: Architecture and Research Guide

## Scope and validity boundary

Agent Economy v2 is a fictional legal-political economy for systems research,
education, and reproducible counterfactual experiments. It is not legal advice,
a court predictor, a financial model, or a forecast of the United States. The
Northstar Federation, its people, firms, tribunals, agencies, and legislation are
fictional. Real records calibrate aggregate targets only.

The `northstar-us-inspired-1.0` ruleset deliberately simplifies contract,
corporate, employment, securities, intellectual-property, and competition law.
It encodes bounded procedures and remedies useful for simulation. It does not
reproduce any jurisdiction's law, patent examination, evidentiary doctrine, or
judicial discretion.

## Authority boundary

The deterministic engine is authoritative for money, ownership, contracts,
obligations, deadlines, market clearing, voting, policy effects, remedies, and
replay. Models can draft, negotiate, argue, plan, and submit a structured action
envelope. The envelope contains an actor, action type, validated payload,
evidence-event references, optional model-call reference, and a short public
rationale. Free text cannot mutate state, and private chain-of-thought is neither
requested nor stored.

```text
model or deterministic policy
        ↓ structured proposal
ActionEnvelope → validator → domain service → ledger/state → append-only event
        ↘ rejected proposal and reason remain auditable
```

All God-mode actions use this path as well. The dashboard can pause, resume,
step, control a participant, queue a typed action, schedule a validated shock,
or fork a checkpoint. It cannot edit SQLite state directly.

## Semantics and migrations

Schema migrations are sequential: v6 legal, v7 startup/IP/M&A, v8 information
and politics, v9 regions/currencies/FX, v10 datasets/scenarios/research
outputs, and v11 wage-offer, IPO-book, and share-movement provenance. Engine
semantics 4 enables legal-institutional behavior, semantics 5 enables regional
multicurrency behavior, and semantics 6 enables bilateral wage bargaining,
qualified agent-priced IPOs, and agent-authored lender-of-last-resort decisions.

Old runs retain their stored semantics. A run is never silently upgraded. Use
an explicit child fork:

```powershell
python run.py --fork RUN_ID@TICK --upgrade-semantics 6
```

The child records its parent and fork tick plus a `semantic_upgrade` event with
the old and new versions.

## Core objects and interfaces

Validated public value objects live in `engine/types.py`: `Money`, `Contract`,
`Clause`, `Obligation`, `LegalMatter`, `LegalDecision`, `Claim`,
`InformationExposure`, `Bill`, `PolicyRuleChange`, `Region`, `FxOrder`,
`DatasetManifest`, `ScenarioPack`, and `ActionEnvelope`.

Contracts follow `draft → offered → negotiating → executed → active`, then
`performed`, `breached`, `terminated`, `expired`, or `disputed`. Executed clauses
compile into deterministic obligations. A breach emits an event; litigation
requires a separate claim. Decisions are validated against jurisdiction,
procedure, evidence, deadlines, burdens, available remedies, and remedy caps.
Invalid model output receives one bounded repair attempt and otherwise leaves
the matter pending.

Financial and ownership effects settle through double-entry transactions and
cap-table writes. Every account and transaction carries a currency. A
multi-currency transaction must balance independently in every currency. Direct
cross-currency transfers are rejected; FX settlement uses finite market-maker
inventories and four balanced legs.

## Living world

The flagship profile persists exactly 1,000 agents:

| Region | Population | Currency | Specialization |
|---|---:|---|---|
| Northstar Federation | 600 | NSD | technology, services, finance |
| Ironvale Union | 220 | IVC | manufacturing, energy |
| Suncoast Republic | 180 | SCD | agriculture, logistics, tourism |

One hundred core agents receive strategic model/scripted turns. Nine hundred
peripheral agents participate through deterministic labor, lifecycle, consumer,
voter, market, and exposure mechanics. Promotion is recalculated every 30 ticks
from office, ownership, wealth, litigation, exposure, and activity. Controlled
participants are pinned.

On the reference Windows development machine, the verified 1,000-agent genesis
completed in about 2.1 seconds. The final offline 365-tick gate completed on
2026-07-13 in 384.651 seconds (6 minutes 25 seconds) with a measured 52.25 MB
peak Python working set and a 643.68 MB SQLite database. It finished at tick 365
with five checkpoints, zero paid spend, exactly 1,000 living agents, exactly 100
living core agents, balanced NSD/IVC/SCD/USD ledgers, no account/ledger-total
mismatches, no negative FX reserve, and zero calls made while an agent was in
the peripheral tier. This passes the 15-minute and 2 GB gates on the reference
machine; downstream release hardware should publish its own measurement.

## Observatory and APIs

The React observatory combines the regional map, flows, core agents, contracts,
obligations, docket, legislation, lobbying, information diffusion, startup
lifecycle, stock/FX markets, and research provenance. Cursor-paginated v2 APIs
are rooted at `/api/v2`:

- `/map`, `/network`, `/legal`, `/politics`, `/information`
- `/startups`, `/markets`, `/datasets`
- `/causal/{event_id}`
- `/god/action`, `/god/fork`

The core `/api/conversations` endpoint supports bounded literal search over
stored message text, topic, and speaker name, with optional agent, tick-range,
cursor, and limit filters. The observatory search box queries the complete run
rather than only the most recent in-memory page.

Static export embeds all required replay data in a single HTML file. It displays
structured rationales and provenance, never private reasoning.

## Dataset provenance

`config/data-manifest.yaml` declares FRED, BLS, Federal Reserve SCF, Census SUSB,
SEC EDGAR, and Congress.gov sources. Each pinned record requires source URL,
retrieval time, release date, vintage date, SHA-256 checksum, transform version,
usage terms, and snapshot path. Missing required vintages and checksum mismatches
fail closed.

The repository pins small FRED and BLS 2020 aggregate targets. SCF, SUSB, EDGAR,
and Congress adapters remain explicitly marked optional/unpinned until a release
operator performs the source-specific refresh and provenance review. Normal runs
and tests never access the network. `--refresh-datasets` is the only refresh path.

Dataset provenance is persisted in schema-v10 tables, returned by `/api/v2/datasets`,
shown in the observatory, and embedded in static replay exports.

## Scenario authoring

Scenario packs are versioned YAML files with:

- a base config and pinned dataset manifest;
- a horizon, common shocks, and at least two arms;
- declared treatment variables and arm-specific typed shocks;
- outcome metrics and a plain-language limitation statement.

`scenarios/2020-pandemic.yaml` compares relief alternatives against shared
health and supply shocks. It validates directional stylized facts only.
`scenarios/ai-competition-merger.yaml` compares control, light, and strict AI
acquisition rules. Its results are explicitly model-conditional.

The counterfactual runner initializes every arm for a seed from identical
pre-treatment state, verifies matching genesis hashes, changes only declared
arm shocks, and defaults to 20 paired seeds. Reports contain distributions,
paired mean effects, standardized effects, deterministic 95% bootstrap
intervals, causal event traces, checksums, and limitations.

## Replay guarantees and invariants

For a fixed code revision, config, semantics version, seed, and recorded model
responses, exact replay must produce the same event hash. Checkpoints persist
engine, persona, and lifecycle PRNG state. Replay does not call a provider.
Canonical replay resolves each persisted `model_call_id` through the logical LLM
call it references, so concurrent completion order cannot create a false mismatch
between otherwise identical databases. News citations are likewise checked
against the deterministic event contents they reference when operational rows
shift physical SQLite IDs. Missing or dangling provenance fails closed.

Required invariants include balanced ledgers per currency, conserved shares,
no enforcement before execution, no remedy outside a validated decision, no
lobbying-funded vote mutation, no article-to-price shortcut, nonnegative FX
inventory, and identical hashes under the same semantics.

Provider calls and the outstanding paid-model v1 acceptance run remain separate
operational gates. No live inference is run without `--approve-live-inference`.
An unperformed paid gate must be reported as pending, never treated as passed.

## Hybrid live pilot

`runs/v2-live-hybrid.yaml` is the bounded provider-acceptance profile. It keeps
30 agents across three regions, four LLM-capable core agents, a compact 4/2
legislature, one live newsroom desk, one conversation pair, a $0.25 simulator
cost cap, and a checkpoint after every tick. MiniMax M3 handles strategic,
legal, financial, regulatory, and political roles; local Ollama
`gemma4:12b` handles newsroom and background generation. The Ollama route
disables the private thinking channel and uses deterministic JSON temperature;
only public response content may enter the event log or replay artifact.
The gateway also recursively removes provider fields such as
`reasoning_content`, `reasoning_details`, and `thinking` before raw response
metadata is persisted, while retaining token and billing counters.

After setting `MINIMAX_API_KEY` and the non-secret local value
`OLLAMA_API_KEY=ollama`, preflight and run the authorized three-tick pilot with:

```powershell
python run.py --config runs/v2-live-hybrid.yaml --preflight-live --approve-live-inference
python run.py --config runs/v2-live-hybrid.yaml --ticks 3 --approve-live-inference
```

Do not scale directly from this profile to 1,000 live agents. First review JSON
validity and repairs, accepted/rejected action proposals, per-provider latency
and token use, cost, per-currency reconciliation, checkpoints, and exact replay.

### Latest bounded acceptance evidence

The three-tick acceptance run `9e43ee6918` at revision `6790919` completed in
about 37 seconds. All 14 provider completions produced valid structured output
without repair or provider failure: 12 MiniMax calls and two local Ollama calls.
The simulator-estimated MiniMax cost was `$0.00473718`; Ollama was local and
recorded zero provider cost. The audit found no persisted private-reasoning
fields, all ledgers reconciled per currency, and all three tick checkpoints were
created. Exact offline replay reproduced the source state hash
`c14c0412aa7e32726de8216c60202ff44de88115f35959d7eb2b4943bed2d347`.

This was an infrastructure and safety result rather than a behavioral-quality
result: all 12 accepted strategic proposals chose `do_nothing`. The seeded gate
below subsequently closed that behavioral coverage gap with live typed actions.

### Seeded behavioral gate

`runs/v2-live-behavioral.yaml` adds a fictional Northstar startup, employee,
pending loan application, VC pitch, breached typed contract, assigned legal
matter, and material-litigation disclosure. The fixture is atomic and submits
every proposal through the normal action executor; the deterministic legal close
detects the breach. Counsel receives only assigned matters, typed remedies, and
referenced public event evidence. `runs/v2-behavioral-rehearsal.yaml` preserves
the same 36-agent fixture while routing every purpose to deterministic policies.

Run the free ten-tick rehearsal first, then explicitly authorize the live gate:

```powershell
python run.py --config runs/v2-behavioral-rehearsal.yaml --ticks 10
python run.py --config runs/v2-live-behavioral.yaml --preflight-live --approve-live-inference
python run.py --config runs/v2-live-behavioral.yaml --ticks 10 --approve-live-inference
```

The first deterministic rehearsal denied an undercapitalized loan, funded the
staffed startup, admitted the contract-breach event, offered a remedy-limited
settlement, published two articles, recorded 72 information exposures, rejected
no actions, and reconciled every currency. Live acceptance additionally requires
private-reasoning redaction, bounded spend, checkpoints, and exact offline replay.

### Latest seeded behavioral evidence

The live ten-tick run `fd0adc5dc1` at revision `9ac38a6` reached its configured
boundary with 48 valid completions: 40 MiniMax M3 calls and eight local Ollama
calls. MiniMax cost `$0.02361318` against the `$0.50` cap; Ollama recorded zero
provider cost. There were no provider failures, invalid contracts, or rejected
actions. Live agents denied the undercapitalized loan, declined the pre-revenue
VC pitch, submitted an admitted breach filing, and offered the requested bounded
settlement. The run also retained one material-litigation disclosure, published
one article, and recorded 36 information exposures.

All 40 LLM-attributed proposals referenced the correct local model call with no
dangling provenance. The persisted provider metadata contained no private
reasoning fields or tags, all ten checkpoint ticks were present, account caches
matched the ledger, and IVC, NSD, SCD, and USD each reconciled to zero. Exact
offline replay `replay-fd0adc5dc1-a29fce4d82` matched every deterministic table
at tick 10 with `differences: []` and source and replay hash
`3586581baea968819cce9fed54b8d9427391645c869f163250c90e7e27976173`.

### Institutional live gate

The completed evidence run used `runs/v2-live-institutional.yaml` for 30 ticks. It
retains the inspectable 36-person behavioral fixture but promotes 22 core agents:
the central banker plus every pinned legal, political, regulatory, market,
credit, venture, and newsroom seat. Its `$2.00` cap is a runaway ceiling. A
scripted twin is available for free shape validation.

```powershell
python run.py --config runs/v2-institutional-rehearsal.yaml --ticks 30
python run.py --config runs/v2-live-institutional.yaml --preflight-live
python run.py --config runs/v2-live-institutional.yaml --ticks 30 --serve --approve-live-inference
```

The served command starts paused. Its Run and Step controls share one absolute
tick-30 boundary, and the header reports the remaining ticks. Live acceptance
requires every configured role to complete, no provider or contract failures,
valid actor-matched provenance, private-reasoning redaction, checkpoints 1-30,
balanced ledgers in every currency, and an exact offline replay.

### Latest institutional live evidence

The 30-tick live run `e09e845b87` executed revision `d0d5797` through the served
dashboard and stopped at its configured boundary. It recorded 737 valid model
calls: 576 MiniMax M3 calls and 161 local Ollama `gemma4:12b` calls. Durable
priced cost was `$0.29012772` against the `$2.00` cap; Ollama cost was zero.
Every configured institutional role completed, including seven paired
reporter/newsroom turns with no duplicate editor decision turn. The dashboard
Step, Run, Pause, Oracle, report, tick-limit, v2 API, and WebSocket terminal-state
paths were also exercised without a browser, console, or network fault.

All 587 proposals were accepted. The run enacted the AI Market Interoperability
Act after seven votes, recorded one self-funded lobbying activity, approved the
seeded merger with an interoperability remedy, and executed one FX trade. It
also denied the undercapitalized loan, declined the VC pitch, retained the
material-litigation disclosure, submitted the assigned legal filing, and
published seven articles. At tick 30 the Oracle recorded a medium-confidence
12% bank-run forecast with a machine-checkable tick-60 resolution rule.

The audit found no provider failures, pauses, invalid contracts, rejected
actions, dangling LLM references, actor/tick provenance mismatches, or persisted
private-reasoning fields or tags. All 30 checkpoint ticks were present, every
account cache matched its ledger, every transaction balanced, SQLite integrity
and foreign keys passed, and IVC, MULTI, NSD, and SCD each reconciled to zero.
Exact offline replay `replay-e09e845b87-19d917217c` reproduced all 737 recorded
calls, all deterministic tables, and the Oracle prediction at tick 30. Source
and replay hash were both
`faf6bd4ada2085dc5ea40e594c0bf03aff2e826fed7715229dca514888907d2a`,
with `differences: []`.

This gate exposed two final provenance/accounting edge cases. Replay now resolves
nested event `source_llm_call_id` values by deterministic call contents and fails
closed on wrong or dangling references. Fresh profiles also charge both Oracle
planning and answer calls to the Oracle carve-out; markerless stored configs keep
their historical split so old capped replays cannot cross a different governor
threshold. No additional paid run is required. The full paid v1 acceptance
campaign and optional external datasets remain separate release work.

### Post-gate literal PRD completion

The subsequent specification audit closed six code-level gaps:

1. The restricted CLI route accepts both `oracle_plan` and `oracle`, while swarm
   purposes remain blocked.
2. Hiring in semantics 6 is a persisted bilateral offer/counter/accept/reject
   protocol; the accepted wage is the payroll wage.
3. Private firms must qualify before opening an IPO book. Issuers choose the
   reserve, investors submit priced bids, and deterministic clearing writes
   balanced cash and primary-share provenance without inventing a price.
4. Fresh profiles publish same-day event-grounded news even on quiet days, and
   stored conversations are searchable across the complete run.
5. End-of-run narrative prose is written by one bounded governed reporter call
   with local provenance and explicit deterministic fallbacks.
6. Reserve distress now creates an immutable request that wakes the central
   banker off cadence. Only an actor-correct, locally model-provenanced
   approve/deny action can grant support or trigger failure and depositor
   haircuts; replay never contacts a provider.

These changes are semantics/config gated where historical behavior affects
replay. Verification completed with 231 Python tests, 16 dashboard tests, a
production dashboard build, a zero-vulnerability npm audit, Python compilation,
and pinned-dataset manifest checks. Free semantics-6 rehearsal `aa828c6542`
reached tick 10 with zero spend and no provider failure. The recorded live run
was then replayed offline as `replay-fd0adc5dc1-a29fce4d82`; it remained exact
with identical ticks and hashes and `differences: []`. No additional paid
provider run was made or is required for this implementation pass.

## Release checklist

Before publication: run Python tests and compilation, dashboard tests/build,
dependency checks, high-severity npm audit, API and browser smoke tests, static
export verification, 30/365-tick performance gates, exact replay, secret scan,
license audit, data-provenance review, and the complete GitHub Actions matrix.
The repository is licensed under Apache-2.0; third-party data retain their own
terms.

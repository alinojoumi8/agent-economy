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
rationale. Free text cannot mutate state. Private chain-of-thought is not part
of the simulation contract: provider reasoning envelopes are recursively
stripped before persistence or exposure, while bounded public rationales remain
auditable.

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
Maintained profiles use semantics 7 for net loan-loss recognition, retirement
liquidity and cadence, deterministic arrival/persona contracts, and autonomous
qualified regional trade and migration. They also schedule fully persisted
peripheral agents through deterministic local policies without model-call rows,
form first stock prices through actor bids/asks, expose only state-qualified
startup work, filter local-currency action surfaces, and count unique workers in
unemployment. Schema remains v11.

Non-regional maintained profiles also persist
`population.baseline_citizens_core: true`, which pins baseline citizens, health
founders, and later arrivals to the fully scheduled core tier under semantics 7.
Regional R19 profiles retain their own core/periphery policy. The marker is
ignored by semantics 1–6, and markerless stored semantics-7 runs retain their
historical peripheral assignment, so replay does not silently acquire new
household decisions.

Old runs retain their stored semantics. A run is never silently upgraded. Use
an explicit child fork:

```powershell
python run.py --fork RUN_ID@TICK --upgrade-semantics 7
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
fully persisted peripheral agents receive scheduled, state-derived local policy
turns without creating model-call records, in addition to deterministic labor,
lifecycle, consumer, voter, market, and exposure mechanics. Promotion is
recalculated every 30 ticks from office, ownership, wealth, litigation, exposure,
and activity. Controlled participants are pinned.

On the reference Windows development machine, the verified 1,000-agent genesis
completed in about 2.1 seconds. The final offline R19 1,000-agent 365-tick
performance gate completed on
2026-07-13 in 384.651 seconds (6 minutes 25 seconds) with a measured 52.25 MB
peak Python working set and a 643.68 MB SQLite database. It finished at tick 365
with five checkpoints, zero paid spend, exactly 1,000 living agents, exactly 100
living core agents, balanced NSD/IVC/SCD/USD ledgers, no account/ledger-total
mismatches, no negative FX reserve, and zero model-call rows for decisions made
while an agent was in the peripheral tier. This passes the 15-minute and 2 GB gates on the reference
machine; downstream release hardware should publish its own measurement.

The historical semantics-7 merge baseline at `c9f0b23` restored a visibly
active observatory
without engine-authored shortcuts: peripheral policy turns create accepted
goods activity, household fundamentals drive the first matched stock price,
qualified partner/founder/lawyer actions complete the startup funding chain and
IP registration, regional contexts reject foreign-currency surfaces until FX,
and unemployment deduplicates workers such as employed founders.

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

The repository pins small FRED/BLS 2020 aggregate targets, a 4,595-family
derivative of the Federal Reserve 2022 SCF public summary extract, and Census
2022 SUSB national employer-firm size classes. EDGAR and Congress remain
optional/unpinned. Normal runs and tests never access the network.
`--refresh-datasets` is the only refresh path; repeat
`--refresh-dataset-key KEY` to refresh selected immutable sources without
repinning unrelated fixtures.

`runs/r21-real-us.yaml` opts into deterministic integer-weight sampling. SCF
`LIQ` funds opening deposits, while `NETWORTH` is an engine-owned off-ledger
calibration baseline because the household ledger models liquid accounts rather
than property and business assets. The agent inspector and event spine expose
the total/liquid/non-liquid split, per-draw sources, and calibrated-versus-
synthetic quantile evidence.

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
shift physical SQLite IDs. Missing or dangling provenance fails closed. The
recorded source opens read-only without initialization or migration, all replay
handles close idempotently, and persisted completed or missed acceptance
checkpoint effects are reconstructed beside their Oracle predictions.

The sanitized portable fixture at
`tests/golden/fd0adc5dc1.sqlite.json.zlib.b64` contains the stored configuration,
recorded requests/responses, and expected deterministic state needed to rebuild
and replay the ten-tick live source without network access. The database itself
records `engine_semantics_version: 5`; an earlier closure plan incorrectly
called it semantics 6. CI preserves the stored semantics rather than rewriting
historical evidence. Fixture format v2 records the source revision honestly as
`unknown-not-recorded`, strips raw provider envelopes and private-reasoning
fields, retains only public text plus cached-input telemetry, and replaces local
repository paths with `repo://`. Reconstruction restores the recorded
`dataset_manifests`, `calibration_targets`, and `scenario_packs` before replay,
so current manifest edits cannot rewrite historical inputs. The fixture artifact
SHA-256 is
`af57eed59e47e9057d7645a65e1bb6f2b579a6a63a377fd6301f33af3955e2d7`; its
normalized replay hash is
`2efcabedba51e4bff3ccfd36393db20d13b41cd5d3e9a3772df42015db4f9170`.

Required invariants include balanced ledgers per currency, conserved shares,
no enforcement before execution, no remedy outside a validated decision, no
lobbying-funded vote mutation, no article-to-price shortcut, nonnegative FX
inventory, and identical hashes under the same semantics.

The pending V9 ten-profile Oracle campaign, live 30-day rumor
pilot, 365-day/$200 acceptance run, and final provenance audit remain separate
operational gates. V9 uses fresh seeds 7381–7390 in odd-control/even-rumor arms,
routes only the Oracle to `MiniMax-M3`, and reuses no earlier campaign source,
response, claim, checkpoint, replay, seed, or receipt. No V9 evidence is claimed
before all ten arms and the aggregate receipt pass. V4 seeds 7331 and 7332 produced eligible
exact source/replay receipts but remain diagnostic evidence because the fixed
campaign did not survive seed 7333.

V4 seed 7333 completed an exact source/replay pair, but its tick-125 forecast
was correctly excluded. Planner attempt 1 requested the government ledger;
runtime returned `entity ledger accounts not found` because the treasury is a
system-owned `sys:gov` account, then incorrectly recorded and retried that
post-preflight execution failure as a planner rejection. Attempt 2 failed the
independently reproducible metric-name contract and attempt 3 succeeded, so the
receipt could not reproduce or bind the first rejection. The v5 boundary used
one tick- and catalog-aware preflight in runtime and receipt audit, maps
government reads to the actual treasury account, and treats a genuine
post-preflight tool failure as an execution failure rather than a retryable plan
rejection.

V5 seeds 7341–7347 subsequently produced eligible exact receipts for their
source/replay pairs. Seed 7348 completed its source but failed exact replay when
duplicated public citation classes at ticks 301 and 331 were mapped through
ambiguous surrogate candidates. Four replay-only newsroom-grounder fallbacks
then propagated into nine information tables; LLM calls, actions, and schedules
still matched. Seeds 7349 and 7350 were never run. The entire v5 campaign is
diagnostic only. The seven receipt-bound replay databases and fourteen Oracle
source/replay receipts belong only to seeds 7341–7347; seed 7348 has no eligible
replay database or Oracle source/replay receipt. Final corrected offline replay
`replay-oracle-calibration-v5-s7348-5220b912ae` reached tick 335 with
`exact: true`, identical logical hash `fee77b65…b378`, all 82 deterministic
tables exact, and `differences: []`; this post-source fix remains diagnostic and
creates no eligible v5 receipt. Cleanup of the v5 database bodies is complete:
320 source checkpoints, 160 fixed-code replay checkpoints, four derived
fixed-replay final databases, and the superseded partial seed-7343 replay were
removed—485 database files and `111.945217 GiB` total. Retained artifacts are
all authoritative final sources; the seven eligible replay databases and
fourteen source/replay receipts for seeds 7341–7347; all source-checkpoint
manifests/hashes, claims, and reports; the 160 fixed-code replay checkpoint
manifests; and the ignored compact final exact receipt. Seed 7348 remains
excluded and has no eligible source/replay receipt or retained replay database.

V6 seed 7351 stopped at tick 65 after a successful Kimi answer returned
`confidence: "medium"` instead of the strict `low|med|high` value. Runtime
persisted `oracle_rule_rejected`, an `insufficient_data` prediction, and
`acceptance_checkpoint_missed`. Spend was $0.18351, with no provider, budget, or
tool-execution failure. V6 is preserved and excluded; seeds 7352–7360 were never
run, and no V6 artifact enters a later corpus.

V7 is archived as an incomplete diagnostic campaign. Seeds 7361–7364 each
retain passed, eligible source receipts and exact 335-tick companion replays with
zero differences. Seed 7365 remains paused at tick 335 in `FINALIZE`; its
authoritative 518,561,792-byte standalone database has SHA-256
`b48b0c5a02270f6b09eafb5c32c8480a44f42057289048faedde9474d8ca8ce5`, passes
immutable read-only `quick_check`, has no WAL/SHM sidecars, and records 32,114
calls, 12 Oracle calls, six resolved forecasts/checkpoints, no critical events,
balanced USD, and `$0.2754108` spend. Receipt production exposed the continuous scheduled-latency floor defect: persisted E2E was 13,658 ms versus a 13,660 ms
governed-call sum. Seed 7365 has no replay or receipt, seeds 7366–7370 were never
run, and V7 has no aggregate manifest or receipt.

The common scheduled-latency producer now clamps both continuous monotonic and
resumed wall-clock duration to at least the sum of conservatively rounded
governed call latencies. Seed 7365's claim binds commit
`7642d7a193f8d0806d6043e8b105b6f469f649c8` and tree
`d9e02a64efd555fb6d0a5c1414351a6db238ad62`, so the source cannot resume or mint
an eligible post-fix receipt. Any post-fix replay would be diagnostic only. No
V7 artifact or seed is reused in V8.

The completed archive cleanup removed exactly the 200 V7 source checkpoint
database bodies matching anchored regex
`^oracle-calibration-v7-s736[1-5]_t\d+\.db$`, reclaiming 49,647,239,168 bytes
(`46.237595 GiB`). No broad V7 wildcard was used. All 360 source/replay
checkpoint manifests and hashes, five final source databases, four final replay
databases, eight source/replay receipt JSONs for seeds 7361–7364, the five
existing claim/initialized-marker pairs for seeds 7361–7365, the profiles,
commitments, template, base, reports, and the authoritative seed-7365 database
were retained.

V8 is archived and excluded. Seeds 7371–7374 produced passed, eligible source
receipts and exact tick-335 companion replays. Seed 7375 stopped at tick 245
after four of six forecasts when Kimi returned HTTP 403 for its exhausted
billing-cycle quota. Its healthy standalone source persisted one
`provider_failure` and spent `$0.19651848`; it is not resumed, repaired, or
substituted. Retain five source databases, four replay databases, eight
source/replay receipts, and all checkpoint manifests. After the archive commit
became durable, conservative cleanup removed exactly 189 V8 source-checkpoint
database bodies—40 each for seeds 7371–7374 and 29 for seed 7375—totalling
43,999,223,808 bytes. Retain 189 source checkpoint manifests, 160 replay
checkpoint manifests, five claims, five initialized markers, and every final
artifact listed above. The verified post-cleanup inventory contains zero
source/replay checkpoint bodies and zero V8 SQLite sidecars. All nine retained
final databases pass immutable read-only `quick_check`, and eligible source/
replay hashes match their receipts. No V8 evidence enters V9.

V9 retains occurrence-aware citation identity, governed-answer repair, engine
semantics 7, and database schema 11. Its fresh version-9 commitment uses seeds
7381–7390 and SHA-256
`8a1845ebe9e916b8618a1c17170dc8a2b439c929ea1e1118670e21683c341a8e`.
Only the Oracle is live through the exact MiniMax provider configuration:
`kind: openai_compat`, `base_url: https://api.minimax.io/v1`,
`api_key_env: MINIMAX_API_KEY`, `healthcheck_path: /models`, `timeout_s: 180`,
`max_tokens_field: max_completion_tokens`, request defaults
`max_completion_tokens: 4096` and `reasoning_split: true`,
`prompt_cache_mode: provider_automatic`, and model `MiniMax-M3`. Standard ≤512k
pricing is `$0.30/M` input, `$1.20/M` output, and `$0.06/M` automatic cache
reads; each arm is capped at `$25`. A disposable one-call probe and a
deliberately unclaimed five-tick Oracle rehearsal succeeded through the exact
adapter, which establishes operational readiness but not V9 corpus evidence.
The complete ten-arm and aggregate gate remains pending.

No live inference is run without `--approve-live-inference`. An unperformed or
failed live gate must be reported as pending or failed, never treated as passed.
PR #20 implementation is authorized for squash merge; live evidence, tagging,
publication, and public deployment require separate authorization.

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

Provider configuration now uses `prompt_cache_mode`: `off`,
`provider_automatic`, `openai_key`, or `anthropic_ephemeral`. Readiness rejects
adapter/mode mismatches, the old `prompt_cache_key` setting remains an
`openai_key` alias, and MiniMax uses automatic prefix caching without an
invented wire field, matching its [OpenAI-compatible prompt-caching
contract](https://platform.minimax.io/docs/api-reference/text-prompt-caching).
Cache telemetry is recorded for cost analysis; a cache miss is not a simulation
failure.

After setting `MINIMAX_API_KEY` and the non-secret local value
`OLLAMA_API_KEY=ollama`, preflight and run the authorized three-tick pilot with:

```powershell
python run.py --config runs/v2-live-hybrid.yaml --preflight-live --approve-live-inference
python run.py --config runs/v2-live-hybrid.yaml --ticks 3 --approve-live-inference
```

Do not scale directly from this profile to 1,000 live agents. First review JSON
validity and repairs, accepted/rejected action proposals, per-provider latency
and token use, cost, per-currency reconciliation, checkpoints, and exact replay.

### Historical bounded acceptance evidence

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

### Historical seeded behavioral evidence (semantics 5)

The live ten-tick run `fd0adc5dc1` reached its configured boundary under its
stored **semantics 5** contract with 48 valid completions; its original source
revision was not recorded and is not inferred. The run contains 40
MiniMax M3 calls and eight local Ollama calls. MiniMax cost `$0.02361318` against
the `$0.50` cap; Ollama recorded zero provider cost. There were no provider
failures, invalid contracts, or rejected actions. Live agents denied the
undercapitalized loan, declined the pre-revenue VC pitch, submitted an admitted
breach filing, and offered the requested bounded settlement. The run also
retained one material-litigation disclosure, published one article, and
recorded 36 information exposures. The run predates semantics 6/7 and is retained
as historical replay evidence, not relabeled as a newer semantic contract.

All 40 LLM-attributed proposals referenced the correct local model call with no
dangling provenance. The persisted provider metadata contained no private
reasoning fields or tags, all ten checkpoint ticks were present, account caches
matched the ledger, and IVC, NSD, SCD, and USD each reconciled to zero. Exact
offline replay `replay-fd0adc5dc1-fa13b78c6d` matched every deterministic table
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

### Historical institutional live evidence

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
was then replayed offline as `replay-fd0adc5dc1-fa13b78c6d`; it remained exact
with identical ticks and hashes and `differences: []`. No additional paid
provider run was made for that earlier semantics-6 implementation pass. The
semantics-7 closure below has its own bounded pilot gate.

### Semantics-7 specification closure

Semantics 7 closes four remaining behavioral contracts without changing schema
v11 or stored semantics 1–6:

1. A default first seizes eligible collateral, then posts only unrecovered
   principal from the bank's same-currency equity account to `SYS_LOSS` as a
   balanced `loan_loss_chargeoff`. The default event reports recovery and net
   charge-off.
2. Retirees can use `withdraw_savings{amount}` only between their own declared,
   same-currency savings and checking accounts. Lifecycle config
   `retirement_liquidity_target_cents` becomes public context field
   `retirement_drawdown_target_cents` beside `savings_balance`; policy draws the shortfall before
   consumption, never seeks work, reads news more frequently, and receives a
   greater conversation-pair weight. Genesis and transitions share the cadence.
3. Due arrivals spawn deterministically during `NIGHT_CLOSE`, funded visibly
   from population inflow with the genesis 70/30 checking/savings split. The
   owned persona wrapper permits exactly one persisted
   `role=persona,purpose=persona` enrichment before morning decisions. Only
   bounded persona traits can change; provider/budget pauses resume, malformed
   success falls back deterministically, and missing replay responses fail closed.
4. Regional prompts include bounded wallet/FX facts, at most five executable
   cross-border trade opportunities, and career-gated migration destinations.
   Trade requires an effective contract, distinct regions, inventory, and
   importer funds and is invoiced in the importer's currency. Scripted founders
   create at most one bounded shipment, while only healthy unemployed
   non-retirees with sufficient numeraire-adjusted wage gain can request migration.

The same pass makes the weighted additive memory formula authoritative, adds
adapter-validated cache modes, and retains logical LLM-reference
canonicalization plus explicit dangling-reference failures.

`runs/v2-spec-closure-rehearsal.yaml` and
`runs/v2-spec-closure-live.yaml` share a five-tick fixture containing a
near-defaulted collateralized loan, retiree, due arrival, qualified shipment,
and qualified migration opportunity. The live profile has a `$1` safety cap;
MiniMax handles persona enrichment and selected strategic roles while background
behavior remains scripted.

```powershell
python run.py --config runs/v2-spec-closure-rehearsal.yaml --ticks 5
python run.py --config runs/v2-spec-closure-live.yaml --preflight-live --approve-live-inference
python run.py --config runs/v2-spec-closure-live.yaml --ticks 5 --approve-live-inference
```

### Semantics-7 closure evidence

The focused named gate passed 86 tests before the final hardening pass; a
93-test integrated adversarial gate passed afterward, and the semantics-7
closure suite passed 280 tests in 165.73 seconds. The post-merge
compatibility/replay cleanup suite passes 303 tests in 178.22 seconds. Python
compilation and pinned-dataset verification were green. At that closure point,
FRED and BLS each supplied three required targets and the four later sources
remained explicitly unpinned. Dashboard verification
installed 80 packages with zero vulnerabilities, passed 16 tests, found zero
high-severity audit vulnerabilities, built 599 Vite modules, confirmed the
committed static bundle was fresh, and passed `git diff --check`.

The preceding replay-integrity revision subsequently passed 590 Python tests with 8
skipped, 23 dashboard tests, a fresh 603-module dashboard build, and checksum
verification for the pinned FRED/BLS/SCF/SUSB datasets. The older counts above remain the historical
semantics-7 merge receipt rather than the later revision total.

The final v3 receipt-hardening tree then passed 599 Python tests with 8 skipped
in 1,618.07 seconds.

The reconciled V9 premerge tree subsequently passed all 663 Python tests with 8
environment-gated skips, 23 dashboard tests, the 603-module production build
and static-bundle freshness check, pinned-dataset verification, dependency
checks, and `git diff --check`.

Free rehearsal `5a0d40d773` completed five ticks at `$0` and exercised every
target effect with zero rejected actions or provider failures. It wrote six
checkpoints and reconciled every currency to zero. Offline replay
`replay-5a0d40d773-b45777cf29` matched tick 5 with `differences: []` and source/
replay hash
`fa190b0dc10a6b94038f7dbd8838a6aea14c1c5b57b691a4788527f8e8cffc34`.

MiniMax-M3 passed live preflight. Live source `b4832032ba` ran schema 11 and
semantics 7 through tick 5 with 57 calls: 21 MiniMax and 36 scripted. Durable
spend was `$0.01121124` (display `$0.0112`) against the `$1` cap. Cached input
was 10,974 of 20,782 input tokens, and all 21 MiniMax calls carried the provider
cache marker. There were zero provider failures; all 42 action proposals were
accepted, including five retirement withdrawals, one shipment, and one
migration.

The loan default wrote 120,000 NSD principal, recovered 5,000, and charged off
the 115,000 net loss. The arrival received the exact 70/30 account split and one
successful governed persona enrichment. The 399,999 IVC shipment delivered at
tick 3, and migration completed at tick 2. Six checkpoints were present, every
currency reconciled to zero, and the privacy/provenance audit found zero
defects. Exact offline replay `replay-b4832032ba-8d99c25c56` matched tick 5 with
`differences: []` and hash
`ec2b24093ad599cca1b9750686a809f28ca08755ca0e4bc3bcbfef861c399ae2`.

Free production-workflow rehearsal `881ed41994` then completed 365 ticks with
exactly 100 living agents, zero spend, balanced ledger state, zero operational
failures, six completed and resolved Oracle checkpoints, all five required
shock traces including the scandal-citing article, the reconciled five-seed
experiment, and three run-bound reviewed phenomena. Its acceptance receipt
passed 19 of 20 checks; only `real_providers` was false because every route was
intentionally scripted. Companion replay `replay-881ed41994-3465cb3101`
matched tick 365 and hash
`37d18cf45365532b39de68efffac68cacb0010ab453734110b8e057e498786ed`;
every deterministic table was exact and `differences: []`. This rehearsal validates
mechanics and evidence plumbing; it does not satisfy live-provider acceptance.

| Gate | Status | Evidence |
|---|---|---|
| Focused + full Python | **Passed** | 86 initial focused / 93 final adversarial / 280 closure / 303 post-merge cleanup; compile and datasets green |
| Dashboard + hygiene | **Passed** | 16 tests, audit 0 high, 599-module build, fresh static bundle, clean diff |
| Free five-tick rehearsal | **Passed** | `5a0d40d773`; exact replay and all deterministic effects |
| Five-tick live pilot | **Passed** | `b4832032ba`; `$0.01121124`, zero failures/defects, all targeted actions accepted |
| Live offline replay | **Passed** | `replay-b4832032ba-8d99c25c56`; equal tick/hash, `differences: []` |
| Preceding replay-integrity revision | **Passed** | 590 Python passed / 8 skipped; 23 dashboard tests; fresh 603-module build; pinned FRED/BLS/SCF/SUSB verification green |
| Current V9 premerge tree | **Passed** | 663 Python passed / 8 skipped; 23 dashboard tests; 603-module build; pinned datasets and hygiene green |
| Free 365-tick workflow rehearsal | **Passed mechanics + replay** | `881ed41994`; 19/20 checks, with only scripted `real_providers` false; replay matched tick/hash with every table exact and `differences: []` |
| GitHub Actions / PR #15 | **Passed and merged** | Exact-head and post-merge dashboard plus Ubuntu/Windows Python 3.11/3.12 matrices passed; merge `255555c2`, post-merge run `29368193807` |

The closure audit also passed the universal hash-locked Python install and
advisory scan, generated dashboard notice freshness/full-text review (including
Vite/Rolldown helpers emitted into the bundle), then-current FRED/BLS terms and
checksum verification, pinned persona prior-art attribution with no copied
upstream code, and both current-tree and full-history secret scans. These checks
authorized PR #15's merge to `main` as
`255555c2b24530c0bd39aed2f501277a468adc0a`; post-merge CI run `29368193807`
repeated all five jobs successfully. Repeat the audits against any future
release candidate.

### Current semantics-7 observatory activity

The later `c9f0b23` hardening pass preserved the four closure contracts and
restored measured activity across the flagship world. Peripheral agents now take
scheduled local policy turns without model-call rows; household fundamentals
create the first stock price through ordinary matched bids and asks; bounded
partner, founder, and lawyer contexts advance pitches through term sheet,
diligence, funding close, and IP; action surfaces remain in the actor's currency
until FX; and unemployment counts each living non-retired worker once. Focused
tests assert each contract and a 31-tick rehearsal proves nonzero goods, trades,
startup/legal activity, and reconciled ledgers.

R21 real-U.S. initialization is now available through
`runs/r21-real-us.yaml`. It uses pinned 2022 SCF family and SUSB firm-size
supports, persists every logical draw and calibration-distance summary, and
replays from source-recorded targets even when the manifest is unavailable.
Recorded gate `24d8dc242e` completed five free ticks with 70 household and 12
realized-firm draws, zero reconciliation failures, and exact offline replay
`replay-24d8dc242e-a9ed4f2910` at hash `95b4b8bd…0cee369a`.
R21 merged through PR #18 at
`21bbf30051e3de8c9b5b7a50e48a0e342d94676a` after all five PR jobs passed.
Post-merge main run `29403186283` repeated all five jobs successfully.

## R22 hosted multi-user boundary

R22 is now implemented as an optional control plane rather than a change to the
simulation kernel. PostgreSQL stores tenants, identities, memberships,
invitations, sessions, run records, writer leases, audit records, and snapshot
pointers under forced row-level security. The serving role must be
`NOSUPERUSER NOBYPASSRLS`. Each run remains one schema-v11 SQLite world, so
local mode, semantics 7, recorded provenance, and exact replay are unchanged.

Registration is invitation-only. Hosted roles are read-only `observer` and
controlling `admin`; mutations require a secure tenant-bound session and CSRF
token, authentication attempts are throttled, and cross-tenant lookups fail as
not found. A lease-based supervisor allows multiple observers and independent
runs but only one writer for each run. Lease loss pauses fail closed, and
restart exposes interrupted runs as paused.

Tick, pause, and stop boundaries can publish immutable checksummed SQLite
snapshots to an absolute local artifact root or S3-compatible storage. Snapshot
verification covers checksum, size, schema, and SQLite integrity before restore.
The authenticated hosted dashboard selects tenant/run context, manages
invitations/members for admins, and maps only supported run controls; local
shock, Oracle, report, participant, and arbitrary file/provider surfaces are not
promoted into hosted mutations.

The reference deployment uses a non-root read-only application image with
PostgreSQL 17, MinIO, an explicit migration job, Caddy TLS, and Prometheus.
`python -m hosted.cli` provides migrate, serve, bootstrap, atomic database
password rotation, snapshot, verify, restore, and readiness operations. Real PostgreSQL/MinIO integration tests are
part of the code gate. `python -m hosted.load_test` adds a bounded HTTPS
own-scope/cross-tenant probe with environment-sourced credentials and sanitized
JSON output; its three focused tests pass. Image/Compose smoke, recorded
real-container multi-user load/isolation evidence, and exact-head CI are
complete. Exact local stack
evidence at `53081f2` passed TLS readiness, two-tenant isolation, immutable S3
snapshot/restore, atomic database-password rotation, Prometheus scraping, and
200/200 bounded load requests including 80 cross-tenant denials. PR #19 head
`1cf1d0a` passed all six jobs in run `29409250171` and merged as `1806294d4`.
Post-merge run `29411023992` contains six zero-step jobs because GitHub blocked
the account for billing/spending-limit reasons; no code ran in that push event.
Any public production deployment remains a separate operational decision and
is not claimed here.

The archived v1 seed-7301 Oracle source completed tick 335 with valid
live-provider provenance but is not acceptance evidence. Its replay diverged
at the first arrival because staged genesis reset an uncheckpointed persona RNG
stream, and checkpoint inspection retained SQLite WAL/SHM sidecars. The
preceding replay-integrity revision persists and validates both semantics-7 RNG
streams, finalizes standalone checkpoints, and enforces the replay target tick;
its focused and full verification passed, and no v1 sample is reused.

The immutable v2 seed-7311 source and generated offline replay both reached
tick 335 and crossed the first arrival without the v1 divergence. Canonical
verification returned `exact: true` with `differences: []`. Receipt generation
then found a separate census-validation defect: the checkpoint audit
counted all stored agent rows instead of validating the living and deceased
populations separately. Preserving one deceased row and creating its replacement
correctly produced 101 stored rows, 100 living agents, and one deceased agent.
V2 is retained as diagnostic evidence and is never resumed, rewritten, or
reused. The receipt correction validates the bounded living population and
requires living plus deceased rows to reconcile to the stored total. It also
authenticates chronological death/schedule/arrival linkage, `NIGHT_CLOSE` phase
and agent-subject provenance, one-time due-schedule consumption, and the fixed
5–20-tick replacement delay.

V3 seed 7321 completed its source and exact companion replay, but its original
receipt admitted only four of six forecasts after applying accepted-plan
validation to authenticated rejected planner attempts. The original receipt
records the pre-inspection source hash; the local source artifact was later
write-opened during diagnosis and is not admissible. It remains excluded
diagnostic evidence and is never reused.

V4 seeds 7331 and 7332 retain eligible exact source/replay receipts as
diagnostic evidence, while seed 7333 and the fixed v4 corpus remain excluded for
the government-ledger retry/provenance failure described above. None of those
sources, responses, claims, checkpoints, replays, or seeds is reused.

V8 is now excluded for the seed-7375 Kimi quota failure described above; its
four completed arms remain diagnostic only. The current pending
`oracle-calibration-v9` campaign is separately precommitted to ten fixed arms
with fresh seeds 7381–7390, odd control and even rumor. Its commitment SHA-256
is `8a1845ebe9e916b8618a1c17170dc8a2b439c929ea1e1118670e21683c341a8e`,
and its manifest template is `runs/oracle/manifest-v9.template.yaml`. It routes
only the Oracle to `MiniMax-M3` through the exact adapter documented above and
retains a `$25` per-run cap. Before live dispatch, each arm consumes an
immutable claim bound to its clean Git commit/tree, committed effective config,
run ID, seed, initialized-state marker, and canonical data location. Source
receipts bind every required checkpoint manifest and the companion replay
tracker; eligibility requires exact one-time source-call consumption with zero
compatibility fallback and zero live replay dispatch. Occurrence-aware citation
mapping keeps repeated public article classes distinct under exact replay,
governed answer semantics use the bounded repair call before persistence, and
the scheduled-latency producer clamps both continuous monotonic and resumed
wall-clock duration to the conservatively rounded governed-call sum. The V9
commitment excludes every earlier campaign profile and evidence path. The local
no-clobber receipt chain is strong accident/tamper evidence, but a public claim
still requires independent signing or a separately administered append-only
transparency log.

Completion of the V9 Oracle campaign, 30-day rumor gate, 365-day/$200 acceptance
run, and final provenance audit remain separate release evidence. PR #20
implementation is authorized for squash merge. Tagging, publication, and public
deployment remain separate release decisions.

## Release checklist

Before publication: run Python tests and compilation, dashboard tests/build,
dependency checks, high-severity npm audit, API and browser smoke tests, static
export verification, 30/365-tick performance gates, exact replay, secret scan,
license audit, data-provenance review, and the complete GitHub Actions matrix.
The repository is licensed under the MIT License; third-party data retain their
own terms.

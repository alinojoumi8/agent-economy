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
qualified regional trade and migration. Schema remains v11.

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

| Gate | Status | Evidence |
|---|---|---|
| Focused + full Python | **Passed** | 86 initial focused / 93 final adversarial / 280 closure / 303 post-merge cleanup; compile and datasets green |
| Dashboard + hygiene | **Passed** | 16 tests, audit 0 high, 599-module build, fresh static bundle, clean diff |
| Free five-tick rehearsal | **Passed** | `5a0d40d773`; exact replay and all deterministic effects |
| Five-tick live pilot | **Passed** | `b4832032ba`; `$0.01121124`, zero failures/defects, all targeted actions accepted |
| Live offline replay | **Passed** | `replay-b4832032ba-8d99c25c56`; equal tick/hash, `differences: []` |
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

R21 real-U.S. initialization is now available through
`runs/r21-real-us.yaml`. It uses pinned 2022 SCF family and SUSB firm-size
supports, persists every logical draw and calibration-distance summary, and
replays from source-recorded targets even when the manifest is unavailable.
Recorded gate `24d8dc242e` completed five free ticks with 70 household and 12
realized-firm draws, zero reconciliation failures, and exact offline replay
`replay-24d8dc242e-a9ed4f2910` at hash `95b4b8bd…0cee369a`.
R22 hosted multi-user operation, the 30-day rumor gate, Oracle
latency/calibration campaign, and 365-day/$200 acceptance run remain separate.
Tagging and publication remain separate release decisions.

## Release checklist

Before publication: run Python tests and compilation, dashboard tests/build,
dependency checks, high-severity npm audit, API and browser smoke tests, static
export verification, 30/365-tick performance gates, exact replay, secret scan,
license audit, data-provenance review, and the complete GitHub Actions matrix.
The repository is licensed under Apache-2.0; third-party data retain their own
terms.

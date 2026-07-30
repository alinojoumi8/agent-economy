# Agent Economy — Implementation Status & PRD Gap Assessment

> **Current assessment date:** 2026-07-30
>
> **Maintained maximum contract for new runs:** schema 17 / semantics 12
>
> **Status authority:** this file is the single maintained release-status
> ledger. Root and World OS specifications define behavior and intended
> direction; historical release receipts prove their named snapshots. Other
> indexes must link here instead of independently labelling a semantics lake
> “released,” “shipped,” or “provider-ready.”
>
> **Compatibility boundary:** stored historical runs retain their recorded
> schema and semantics. Supporting schema 17 / semantics 12 for new runs does
> not rewrite or upgrade historical evidence.

## Status terminology

| Term | Meaning in this repository |
|---|---|
| **Implemented** | Code and repository tests exist for the named opt-in contract. |
| **Locally verified** | The named deterministic, replay, security, or browser evidence has passed locally. |
| **Released baseline** | The project has designated the lake as an admissible maintained baseline; this does not imply public hosting. |
| **Rollout-gated** | Code exists, but named operational or independent evidence is still required before hosted/public use. |
| **Historical receipt** | Immutable evidence for the dated code/profile/provider conditions only; it is not a claim about current credentials or later semantics. |

## Current semantics and release matrix

| Contract | Implementation state | Release state | Remaining boundary |
|---|---|---|---|
| Semantics 1–7 / schemas through 11 | Implemented and maintained for recorded-run compatibility | Historical PRD-v1 and semantics-7 baselines | New features do not alter their phase, replay, or information contracts. |
| Semantics 8 / schema 12 | Communications and Causal Observatory implemented and locally verified | **Released deterministic causal baseline** | Its dated provider-smoke receipt remains historical and unavailable; later MiniMax evidence is separate and does not retroactively change that receipt. |
| Semantics 9 / schema 13 | External Agent Gateway, scoped identity, REST/MCP, receipts, and replay implemented | **Rollout-gated** | Independent MCP conformance plus real Hermes, OpenClaw, Python, and TypeScript connector receipts are pending. |
| Semantics 10 / schema 14 | Agent Commons, deterministic feeds, explicit-read exposure, moderation, and replay implemented | **Rollout-gated** | The frozen feed/read experiment, UI evidence, and hosted operational gate remain pending. |
| Semantics 11 / schema 15 | Compute plans, sponsorship, provider pools, operational attempt evidence, and learnable skills implemented and locally verified | Implemented opt-in contract; no separate public-hosting claim | Public use inherits the Semantics 9–10 hosted rollout gates. |
| Semantics 12 / schema 17 | Civic places, presence, queues, appointments, permits, attention, privacy, gateway, and replay contracts implemented and locally verified | Implemented opt-in contract; current maintained maximum | Public use inherits the Semantics 9–10 hosted rollout gates. |

## Current executive verdict

The PRD-v1 P0/P1 surfaces and R18–R22 extensions are implemented. The current
runtime also contains the Semantics 8–12 code summarized above. There is no
additional functional PRD-v1 feature gap.

What remains is release and product evidence rather than another core economic
subsystem: independent external-connector receipts, the Semantics 10 rollout
evidence, the fresh V9 Oracle campaign, the corrected live rumor gate, the
explicitly authorized long live campaign, and a fresh provenance, license,
dependency, and secret audit before tagging or public deployment.

The remainder of this document preserves the dated closure and campaign
evidence. Version labels inside those sections describe the run or release
snapshot being evidenced; they must not be read as the current maximum
schema/semantics contract.

## Historical semantics-7 closure matrix (2026-07-18 snapshot)

The semantics-7 closure merged as
`255555c2b24530c0bd39aed2f501277a468adc0a`; post-merge CI run `29368193807`
repeated all five jobs successfully. No tag or publication was performed, and
those actions remain separate release decisions.

| Surface | Implemented contract | Repository evidence | Final evidence state |
|---|---|---|---|
| Versioning | Maintained profiles select semantics 7; stored semantics 1–6 retain historical behavior; explicit forks may opt in; schema remains v11. Unsupported future semantics and schemas fail closed. | [Base profile](../runs/base.yaml), [v2 profile](../runs/v2.yaml), replay compatibility tests | **Passed:** 86 initial focused, 93 final adversarial, 280-test closure, 303-test post-merge cleanup, the preceding 590-test release-gate suite, the 599-test v3 receipt-hardening suite, and the current 663-test V9 premerge suite; 8 environment-gated skips |
| Bank defaults | Eligible collateral is seized first. Only unrecovered principal is posted from the bank's currency-matched equity account to `SYS_LOSS` through balanced `loan_loss_chargeoff`; the existing default event reports recovered and net charged-off cents. | [Credit engine](../engine/credit.py), [semantics-7 credit tests](../tests/test_credit_semantics7.py) | **Passed:** live 120,000 NSD default, 5,000 recovery, 115,000 net charge-off |
| Retirement | `withdraw_savings{amount}` is retiree-only and moves funds between the actor's own declared, same-currency savings/checking accounts. Config `retirement_liquidity_target_cents` becomes public `retirement_drawdown_target_cents` beside `savings_balance`; pre-consumption drawdown, no job search, retired cadence, and stronger conversation participation are semantics-7-only. | [Action executor](../engine/actions.py), [lifecycle](../engine/lifecycle.py), [retirement tests](../tests/test_retirement_semantics7.py) | **Passed:** five targeted live withdrawals; no rejected proposals |
| Arrivals and personas | Due arrivals spawn deterministically during `NIGHT_CLOSE`, use visible population inflow and a 70/30 checking/savings split, then receive exactly one governed `role=persona,purpose=persona` call before their first morning decision. Enrichment is bounded; malformed success falls back deterministically; provider/budget pauses resume; missing recorded replay responses fail closed. | [Owned persona wrapper](../agents/personas/library.py), [world loop](../world/loop.py), [arrival tests](../tests/test_arrival_personas.py) | **Passed:** exact 70/30 live split, one enriched persona call, zero provenance defects |
| R20 autonomy | Regional context exposes bounded FX/wallet facts, at most five executable trade opportunities, and career-gated migration options. Trade requires an effective cross-region contract, inventory, and importer funds and is invoiced in the importer's currency. Migration requires a healthy unemployed non-retiree, wage threshold, authorization, and no disqualifying credit exposure. | [Region engine](../engine/regions.py), [regional tests](../tests/test_v2_regions.py) | **Passed:** 399,999 IVC shipment delivered tick 3; migration completed tick 2 |
| Measured observatory activity | Scheduled peripheral agents run local state-derived policies without `llm_calls`; bootstrap listings gain a first price only through household bids/asks derived from fundamentals; state-qualified partner/founder/lawyer actions advance pitch → term sheet → diligence → round close and IP; local-currency contexts reject foreign IDs until FX; unemployment deduplicates living non-retired workers. | [Policies](../agents/policies.py), [prompt contexts](../agents/prompts.py), [startup engine](../engine/startups.py), [metrics](../world/metrics.py), [behavioral gate](../tests/test_v2_behavioral_gate.py) | **Passed:** targeted 31-tick rehearsal has GDP, trades, index, term sheets, diligence, funded rounds, IP, bounded unemployment, and reconciled ledgers |
| Replay fixture | Physical LLM row IDs canonicalize through deterministic referenced-call content; missing/dangling/wrong logical references fail. Recorded sources open read-only without migration or lingering locks. Completed/missed acceptance orchestration effects replay exactly. Fixture v2 strips raw provider envelopes, uses `repo://` paths, and restores recorded dataset/calibration/scenario inputs instead of current manifests. | [Verifier](../world/replay_verify.py), [portable fixture test](../tests/test_recorded_replay_golden.py), [source lifecycle tests](../tests/test_replay_source_lifecycle.py), [acceptance tests](../tests/test_acceptance.py) | **Passed:** semantics-5 fixture artifact `af57eed5…952d7`, normalized replay `2efcabed…f9170`, semantics-7 replays exact, source hash/schema unchanged |
| Prompt caching | `prompt_cache_mode` supports `off`, `provider_automatic`, `openai_key`, and `anthropic_ephemeral`; adapter/mode mismatches fail readiness; legacy `prompt_cache_key` aliases keyed OpenAI mode; cached-token billing is retained. | [Adapters](../llm/adapters.py), [readiness](../llm/readiness.py), [cache tests](../tests/test_prompt_caching.py) | **Passed:** 10,974/20,782 cached input tokens; all 21 MiniMax calls marked cached |
| Memory ranking | Retrieval uses the authoritative weighted sum `0.5·recency_decay + 0.3·importance + 0.2·relevance`, with a regression that distinguishes it from multiplication. | [Memory](../agents/memory.py), [ranking test](../tests/test_memory_ranking.py) | **Passed:** focused and full regression gates |
| Closure profiles | Paired five-tick profiles seed a near-defaulted loan, retiree, due arrival, qualified shipment, and migration opportunity. The live profile routes persona/selected strategic work to MiniMax, keeps background behavior scripted, and caps spend at `$1`. | [Rehearsal](../runs/v2-spec-closure-rehearsal.yaml), [live pilot](../runs/v2-spec-closure-live.yaml), [fixture seeder](../world/spec_closure_fixture.py) | **Passed:** `5a0d40d773` and `b4832032ba`, both exact offline replay |

## Historical R18–R22 extension record

| Requirement | Disposition | Current status | Remaining boundary |
|---|---|---|---|
| **R18 — Participant mode** | Implemented extension | One controlled citizen uses the normal action validator/ledger with durable queued/executed/rejected/cancelled history and replay-safe provenance. | Participant-influenced runs remain disqualified from observer-only acceptance. |
| **R19 — 1,000-agent scale** | Implemented extension | Model-capable strategic core plus fully persisted deterministic periphery with scheduled local policy turns, zero peripheral model-call rows, promotion/demotion, regional genesis, conserved balances, replay, observatory, and a recorded performance gate. | Downstream release hardware should publish its own benchmark. |
| **R20 — Regions, trade, migration, FX** | Implemented extension | Multicurrency ledgers, regional markets, FX inventory, shipments, migration, API/UI/report/replay surfaces, and semantics-7 autonomous opportunity context are implemented. | Five-tick rehearsal/live gates and exact replay passed. |
| **R21 — Real-data calibration** | Implemented extension | Explicit `real_us` mode deterministically samples pinned 2022 SCF income, liquid-holding, and total-net-worth records plus 2022 SUSB employer-firm classes, records per-draw provenance and distance evidence, and replays from recorded targets without a manifest. | `LIQ` funds deposits; SCF total net worth is an engine-owned off-ledger calibration baseline visible in the inspector. Identities stay fictional and default mode stays synthetic. |
| **R22 — Hosted multi-user service** | Implemented extension; local acceptance passed | PostgreSQL tenant/user/membership/session/invite/run/lease/audit catalog with forced RLS; invite-only observer/admin auth; CSRF/throttling; single-writer supervisor; one SQLite v11 world per run; immutable local/S3 snapshots; hosted dashboard; Compose/Caddy/Prometheus; migrations and backup/verify/restore CLI; isolated PostgreSQL/MinIO integration coverage; bounded sanitized HTTPS load/isolation probe. | Exact local Compose/load/restore/rotation evidence passed at `53081f2`; all six PR #19 jobs passed at `1cf1d0a` in run `29409250171`. Local mode and engine schema/semantics are unchanged. Public deployment is not claimed. |

## Historical recorded-run evidence

Live run `fd0adc5dc1` completed ten ticks with 48 valid completions, `$0.02361318`
MiniMax spend, no provider failures or rejected actions, ten checkpoints, valid
local provenance, no stored private-reasoning fields, and balanced IVC/NSD/SCD/USD
ledgers. Final-code offline replay `replay-fd0adc5dc1-fa13b78c6d` matched at
tick 10 with `differences: []` and hash
`3586581baea968819cce9fed54b8d9427391645c869f163250c90e7e27976173`.

The source database records **semantics 5**, not semantics 6. It proves portable
historical response replay and the credit/VC/legal/disclosure behavioral gate; it
does not prove semantics-7 behavior. Its source revision was not recorded and is
reported as `unknown-not-recorded`. Portable fixture format v2 removes raw
provider envelopes/private-reasoning fields, keeps public text and cached-input
telemetry, rewrites repository paths as `repo://`, and restores recorded
`dataset_manifests`, `calibration_targets`, and `scenario_packs`. Its artifact
SHA-256 is
`af57eed59e47e9057d7645a65e1bb6f2b579a6a63a377fd6301f33af3955e2d7`; the
normalized reconstructed replay hash is
`2efcabedba51e4bff3ccfd36393db20d13b41cd5d3e9a3772df42015db4f9170`.

The 30-tick institutional run `e09e845b87` remains separate historical evidence:
737 valid recorded calls, `$0.29012772` priced spend, no provider/rejection/
provenance/redaction failures, checkpoints 1–30, balanced currencies, and exact
offline replay. It remains separate from the current five-tick closure gate.

## Historical semantics-7 run evidence

Free rehearsal `5a0d40d773` completed tick 5 at zero spend with every target
effect, zero rejected actions/provider failures, six checkpoints, and every
currency balanced. Exact replay `replay-5a0d40d773-b45777cf29` returned
`differences: []` with hash
`fa190b0dc10a6b94038f7dbd8838a6aea14c1c5b57b691a4788527f8e8cffc34`.

MiniMax-M3 passed preflight. Live source `b4832032ba` completed schema 11 /
semantics 7 tick 5 with 57 calls (21 MiniMax, 36 scripted) and `$0.01121124`
spend. Cached input was 10,974/20,782 tokens and all 21 MiniMax calls carried a
cache marker. All 42 proposals were accepted: five withdrawals, one shipment,
and one migration among the targeted paths. The default recovered 5,000 of
120,000 NSD and charged off 115,000; the arrival had an exact 70/30 split and
one enriched persona call; the 399,999 IVC shipment delivered at tick 3; and
migration completed at tick 2. Six checkpoints, every currency, and all privacy/
provenance checks were clean. Exact replay `replay-b4832032ba-8d99c25c56`
returned `differences: []` with hash
`ec2b24093ad599cca1b9750686a809f28ca08755ca0e4bc3bcbfef861c399ae2`.

### Full acceptance-workflow rehearsal

Free rehearsal `881ed41994` completed 365 ticks with exactly 100 living agents,
zero spend, balanced ledger state, zero operational failures, six completed and
resolved Oracle checkpoints, all five required shock traces (including the
scandal-citing article), the reconciled five-seed experiment, and three distinct
run-bound reviewed phenomena. Its acceptance receipt passed 19 of 20 checks;
only `real_providers` was false because every route was intentionally scripted.
This validates the deterministic mechanics and evidence pipeline, not the live
365-day release gate. Companion replay `replay-881ed41994-3465cb3101` matched
tick 365 and hash
`37d18cf45365532b39de68efffac68cacb0010ab453734110b8e057e498786ed`;
every deterministic table was exact and `differences: []`.

## PRD-v1 acceptance boundary

All P0/P1 and R18–R22 code surfaces are implemented, with no additional
functional feature gap. The archived `oracle-calibration-v1-s7301` source
completed tick 335 with valid live-provider provenance, but its offline replay
diverged at the first arrival because staged genesis reset an uncheckpointed
persona RNG stream. Checkpoint inspection also retained SQLite WAL/SHM
sidecars. The source is diagnostic evidence only and is not acceptance
evidence. The preceding replay-integrity revision persists and validates both semantics-7
RNG streams, finalizes standalone checkpoints without sidecars, and enforces the
replay target tick. Focused, representative aggregate, and full gates pass.

The immutable v2 seed-7311 source and generated offline replay both reached
tick 335 and crossed the first arrival without the v1 divergence. Canonical
verification returned `exact: true` with `differences: []`. Receipt generation
then failed because checkpoint integrity required exactly 100 total
agent rows even after lifecycle correctly preserved one deceased row and added
its replacement arrival, yielding 101 stored rows, 100 living, and one deceased.
V2 is retained as diagnostic evidence and is never resumed, rewritten, or
reused. The current correction validates the bounded living population and
reconciles living plus deceased rows to the stored total. It also validates
chronological death/schedule/arrival linkage, `NIGHT_CLOSE` phase and subject
provenance, one-time due-schedule consumption, and the fixed 5–20-tick delay;
its verification is part of the fresh campaign gate.

Four release-quality workstreams remain after the extension closure:

1. run the fresh v9 ten-profile Oracle evidence campaign with seeds 7381–7390,
   only the Oracle live through `minimax/MiniMax-M3`, standard ≤512k pricing
   pinned at $0.30/M input, $1.20/M output, and $0.06/M cached input,
   `provider_automatic` caching, and a $25 per-run cap; commitment SHA-256 is
   `8a1845ebe9e916b8618a1c17170dc8a2b439c929ea1e1118670e21683c341a8e`;
   its explicit read-only manifest evaluator, 60-forecast floor,
   outcome-diversity gate,
   end-to-end timer, strict resolver/provenance checks, and deterministic
   JSON/Markdown receipts are implemented, but no V9 live evidence is yet
   claimed;
2. run the corrected 30-day live rumor gate;
3. run the explicitly authorized 365-day/$200 campaign; production now starts
   with exactly 100 living agents and evaluates living population separately
   from preserved deceased rows; and
4. a fresh release-candidate provenance/license/dependency/secret audit.

The implementation in PR #20 is authorized for squash merge after its complete
local gate. Tagging, publication, and public deployment require separate
authorization after the live gates pass.

The five-tick semantics-7 pilot and scripted 365-tick rehearsal supplement
those gates; neither replaces live-provider acceptance. R21's SCF/SUSB supports
are pinned; unrelated optional sources remain separate.

## Historical semantics-7 verification snapshot

| Check | Result |
|---|---|
| Current 2026-07-18 documentation sweep | **Passed:** 84 focused documentation/current-behavior tests; full suite **489 passed, 8 skipped in 202.49s**; compileall; all pinned datasets; `pip check`; Python advisory audit; **23 dashboard tests**; npm audit 0; notice freshness; 603-module production build with byte-identical committed bundle. |
| Checkpoint baseline | Existing six-feature work was checkpointed after **231 Python tests**, **16 dashboard tests**, dashboard build, and `git diff --check` passed. |
| Focused semantics-7 tests | **Passed:** 86 tests across credit, retirement, arrival/persona, R20, replay, cache, memory ranking, pause/resume, and portability; then 93 integrated adversarial tests after final fixes. |
| Full Python / data | **Passed:** reconciled V9 premerge tree 663 passed / 8 skipped, with compilation and pinned FRED/BLS/SCF/SUSB verification green. The historical v3 receipt-hardening tree passed 599 / 8 in 1,618.07 seconds and the preceding replay-integrity tree passed 590 / 8. Historical receipts: semantics-7 closure 280, post-merge cleanup 303, and R21 integrated gate 328. |
| Dashboard / hygiene | **Passed:** current branch 23 tests and a fresh 603-module build. Historical closure evidence: 16 tests, npm audit 0, license notice check, 599-module build byte-identical twice, static bundle fresh, clean diff. |
| Portable `fd0adc5dc1` fixture | **Passed:** sanitized v2 artifact restored/replayed offline with networking prohibited under stored semantics 5 and normalized hash `2efcabed…f9170`. |
| Free closure rehearsal | **Passed:** `5a0d40d773`, all targets, six checkpoints, balanced currencies, exact replay. |
| Bounded live pilot | **Passed:** MiniMax ready; `b4832032ba`, `$0.01121124`, all 42 proposals accepted, zero provider/privacy/provenance failures. |
| Live offline replay | **Passed:** `replay-b4832032ba-8d99c25c56`, tick/hash identical, `differences: []`. |
| R21 recorded replay | **Passed:** `24d8dc242e` sampled 70 households and 12 realized firms through tick 5 with zero reconciliation failures; `replay-24d8dc242e-a9ed4f2910` matched hash `95b4b8bd…0cee369a`. |
| R21 merge | **Passed:** PR #18 passed all five PR jobs and merged as `21bbf30051e3de8c9b5b7a50e48a0e342d94676a`; post-merge main run `29403186283` repeated all five successfully. |
| R22 code/integration surface | **Passed:** exact local stack evidence at `53081f2` covered TLS, tenant isolation, immutable S3 snapshots/cold restore, password rotation, Prometheus, and 200/200 load requests with 80 cross-tenant denials; PR #19 head `1cf1d0a` passed dashboard, hosted PostgreSQL/S3, and Ubuntu/Windows Python 3.11/3.12 in run `29409250171`. |
| R22 merge / post-merge runner | **Merged:** PR #19 became `1806294d4fecbe13ddbdf615c459755c74293599`. Push run `29411023992` has six zero-step jobs; GitHub's annotations identify account billing/spending-limit state, so no repository code was executed. |
| Archived Oracle v1 seed 7301 | **Failed acceptance / retained diagnostic:** the source completed tick 335 with six resolved forecasts and valid live-provider provenance, but its replay diverged at the first arrival because staged genesis reset an uncheckpointed persona RNG stream. Read-only checkpoint inspection also retained SQLite sidecars. It is not reusable acceptance evidence. |
| Replay-integrity correction | **Passed locally:** engine plus persona RNG state persists under semantics 7; staged genesis and checkpoints require column-specific valid RNG shapes; standalone SQLite checkpoints contain no WAL/SHM sidecars; replay fails when the target tick is not reached. Focused regressions, representative aggregate receipts, the preceding 590-test gate, the 599-test v3 gate, and the current 663-test V9 premerge gate pass. |
| Archived Oracle v2 seed 7311 | **Failed receipt / retained diagnostic:** source and generated replay reached tick 335 and canonical verification returned `exact: true` with `differences: []`, but the receipt incorrectly treated total stored rows as living population after a deceased row was preserved and a replacement arrived. The immutable v2 evidence is never reused. |
| Archived Oracle v3 seed 7321 | **Failed receipt / excluded diagnostic:** source and exact companion replay completed, but the original receipt admitted only four of six forecasts because it applied accepted-plan validation to authenticated rejected planner attempts. The original receipt records the pre-inspection source hash. The local source artifact was later write-opened during diagnosis and is not admissible; no v3 artifact is reused. |
| Archived Oracle v4 seeds 7331–7333 | **Excluded fixed corpus / retained diagnostic:** seeds 7331 and 7332 produced eligible exact source/replay receipts, but no v4 campaign evidence is reused. Seed 7333 completed an exact pair, yet its tick-125 forecast was correctly ineligible. Attempt 1 asked for the government ledger; runtime looked only for `accounts.owner_type='gov'`, missed the system-owned `sys:gov` treasury, returned `entity ledger accounts not found`, and mislabeled/retried that post-preflight execution failure as a planner rejection. Attempt 2 failed the independently reproducible metric-name contract and attempt 3 succeeded, so the receipt could not reproduce or bind attempt 1. The forecast, run, and fixed v4 corpus remain excluded; no v4 source, response, claim, checkpoint, replay, or seed is reused. |
| Oracle v2–v4 storage archive | **Completed conservative cleanup:** 200 superseded checkpoint database bodies were removed after diagnosis—40 for v2, 40 for v3, and 120 for v4—recovering `45.369270 GiB`. All 200 runtime checkpoint manifests and every final source/replay database remain. These campaigns stay excluded diagnostic evidence. |
| Archived Oracle v5 seeds 7341–7350 | **Excluded fixed corpus / retained diagnostic:** seeds 7341–7347 produced passed, eligible source receipts with exact companion replays. Seed 7348 finalized its source, but duplicate same-tick loan defaults collapsed to ambiguous public citation classes during replay. Four newsroom articles failed closed to deterministic daily briefs at ticks 301 and 331, cascading through nine information tables. Seeds 7349–7350 were never run. Final corrected offline replay `replay-oracle-calibration-v5-s7348-5220b912ae` reached tick 335 with `exact: true`, identical logical hash `fee77b65…b378`, all 82 deterministic tables exact, and `differences: []`; the post-source fix is diagnostic proof only and creates no eligible v5 receipt. Completed cleanup removed 320 v5 source-checkpoint database bodies, 160 fixed-code replay checkpoint bodies, four derived fixed-replay final databases, and the superseded partial seed-7343 replay: 485 database files and `111.945217 GiB` total. Retained artifacts are all authoritative final sources; the seven eligible replay databases and fourteen source/replay receipts for seeds 7341–7347; all source-checkpoint manifests/hashes, claims, and reports; the 160 fixed-code replay checkpoint manifests; and the ignored compact final exact receipt. Seed 7348 remains excluded and has no eligible source/replay receipt or retained replay database. No v5 artifact or seed enters a later corpus. |
| Archived Oracle v6 seeds 7351–7360 | **Excluded after first arm / retained diagnostic:** seed 7351 stopped at tick 65 after a successful Kimi answer returned `confidence: "medium"` instead of the strict `low|med|high` value. Runtime persisted `oracle_rule_rejected`, an `insufficient_data` prediction, and `acceptance_checkpoint_missed`. Spend was `$0.18351`; there was no provider, budget, or tool-execution failure. V6 is preserved and excluded, seeds 7352–7360 were never run, and no v6 artifact or seed enters a later corpus. |
| Scheduled-latency producer | **Corrected for the current tree:** `scheduled_e2e_v1` still covers Oracle planning, bounded reads, answering, and validation. Its common producer now clamps both continuous monotonic and resumed wall-clock duration to at least the sum of conservatively rounded governed call latencies. Engine semantics 7 and database schema 11 are unchanged. |
| Archived Oracle v7 seeds 7361–7370 | **Incomplete / retained diagnostic:** seeds 7361–7364 each produced passed, eligible source receipts and exact 335-tick companion replays with zero differences. Seed 7365's authoritative 518,561,792-byte standalone database (`b48b0c5a02270f6b09eafb5c32c8480a44f42057289048faedde9474d8ca8ce5`) passes immutable read-only `quick_check`, has no WAL/SHM sidecars, and remains paused at tick 335 in `FINALIZE`. It records 32,114 calls, 12 Oracle calls, six resolved forecasts/checkpoints, no critical events, balanced USD, and `$0.2754108` spend. Receipt production exposed the continuous scheduled-latency floor defect: persisted E2E was 13,658 ms versus a 13,660 ms governed-call sum. Seed 7365 has no replay database or receipt; seeds 7366–7370 were never run; no aggregate V7 manifest or receipt exists. Its claim binds commit `7642d7a193f8d0806d6043e8b105b6f469f649c8` and tree `d9e02a64efd555fb6d0a5c1414351a6db238ad62`, so it cannot resume or mint an eligible post-fix receipt. No V7 artifact or seed enters V8. |
| Oracle v7 storage archive | **Completed conservative cleanup:** exactly 200 source checkpoint database bodies in `data/checkpoints` matching anchored regex `^oracle-calibration-v7-s736[1-5]_t\d+\.db$` were removed, reclaiming 49,647,239,168 bytes (`46.237595 GiB`). All 360 source/replay checkpoint manifests and hashes, five final source databases, four final replay databases, eight source/replay receipt JSONs for seeds 7361–7364, the five existing claim/initialized-marker pairs for seeds 7361–7365, the profiles/commitments/template/base, reports, and authoritative seed 7365 database remain retained. |
| Archived Oracle v8 seeds 7371–7380 | **Excluded fixed corpus / retained diagnostic:** seeds 7371–7374 produced passed, eligible source receipts with exact tick-335 companion replays and zero differences. Seed 7375 stopped at tick 245 after Kimi returned a billing-cycle usage-limit failure. Its persisted `provider_failure` makes the arm ineligible, so V8 cannot satisfy its immutable ten-arm corpus and is never resumed, substituted, or pooled into V9. Seeds 7376–7380 were never run. |
| Oracle v8 storage archive | **Completed conservative cleanup:** exactly 189 source checkpoint bodies matching anchored regex `^oracle-calibration-v8-s737[1-5]_t\d+\.db$`—40 each for seeds 7371–7374 and 29 for seed 7375—were removed, reclaiming 43,999,223,808 bytes. Five source databases, four replay databases, 189 source checkpoint manifests, 160 replay checkpoint manifests, five claims, five initialized markers, eight source/replay receipts, reports, and campaign configurations remain retained. Source/replay checkpoint bodies and SQLite sidecars remaining: zero. All nine final databases pass immutable read-only `quick_check`, and eligible source/replay hashes match their receipts. |
| Oracle campaign tooling | **Implemented; V9 live evidence pending:** ten fresh profiles for seeds 7381–7390 and `runs/oracle/manifest-v9.template.yaml` define campaign `oracle-calibration-v9`, version 9. Odd seeds are control and even seeds rumor arms. Only the Oracle is live through `minimax/MiniMax-M3`; background behavior remains scripted. The route pins standard ≤512k pricing at $0.30/M input, $1.20/M output, and $0.06/M cached input, uses `provider_automatic` caching, and retains a $25 per-run cap. Commitment SHA-256 is `8a1845ebe9e916b8618a1c17170dc8a2b439c929ea1e1118670e21683c341a8e`. Claims bind clean Git commit/tree, committed config, initialized state, canonical source/replay paths, checkpoint manifests, and exact one-time replay consumption with zero fallback/live dispatch. Runtime and receipt share the fixed scheduled-latency producer and existing fail-closed preflight/provenance rules. No V8 artifact or seed enters V9, and no V9 live evidence is claimed before all ten arms and the aggregate receipt pass. Engine semantics 7 and schema 11 are unchanged. |
| Oracle free arm rehearsal | **Passed mechanics:** control `9fb8985f97` resolved six negatives; treatment `bb877a0d89` fired all six public precursors and all six larger rumors and resolved six positives. Both reconciled with zero provider/budget/report failures; their combined scripted Brier score was `0.19469025`. Treatment replay `replay-bb877a0d89-385256e2a1` matched tick 335 and hash `0ff7685e…2fa9ed` with `differences: []`. Scripted provenance remains intentionally ineligible for the live receipt. |
| Free 365-tick workflow rehearsal | **Passed mechanics + replay:** `881ed41994` passed 19/20 acceptance checks with only scripted `real_providers` false; 100 living agents, six resolved Oracle checkpoints, every shock trace, experiment evidence, and three reviewed phenomena. `replay-881ed41994-3465cb3101` matched tick 365 and hash `37d18cf4…498786ed` with every deterministic table exact and `differences: []`. |
| Earlier closure CI / PR | **Passed:** PR #15 exact-head and post-merge dashboard plus Ubuntu/Windows Python 3.11/3.12 matrices; merge `255555c2`, post-merge run `29368193807`. |

## Closure audit evidence

- Python installs use the universal SHA-256-pinned `requirements.lock`; lock
  regeneration was byte-identical and Python 3.11/3.12 Windows/Linux hash
  resolution passed. `pip check` and the Python advisory audit are clean.
- Dashboard notices contain full license texts for runtime dependencies plus
  Vite/Rolldown helpers emitted into the artifact. Notice generation/freshness,
  high-severity npm audit, and two consecutive byte-identical builds pass.
- FRED/BLS aggregate snapshots plus the SCF/SUSB R21 supports verify against
  checksums with precise source/terms metadata. Adapter, malformed-input,
  deterministic-sampling, provenance, reconciliation, API, and exact-replay
  regressions are committed in `tests/test_r21_calibration.py`.
- The persona generator is locally authored synthetic heuristic code with pinned
  prior-art attribution; no upstream persona source was copied or vendored.
- Narrow Gitleaks allowlisting preserves the generic-key rule. Current-tree and
  full-history scans, plus a synthetic negative control, pass with zero secrets.

These results authorized PR #15's code merge only. Repeat the provenance,
license, dependency, and secret audit against the release candidate before a
public tag.

## Release constraints and deferred campaigns

- PR #15 merged after its exact-head matrix passed, and post-merge CI run
  `29368193807` passed all five jobs. No tag or publication was performed.
- R21 real-U.S. calibration merged through five-job-green PR #18, and
  post-merge main run `29403186283` passed all five jobs. R22 hosted
  multi-user code and local acceptance evidence are complete; PR #19 run
  `29409250171` passed all six jobs and merged as `1806294d4`. Its post-merge
  workflow was blocked before execution by GitHub account billing. Handbook PR
  #24 later passed the dashboard, hosted integration, and complete
  Ubuntu/Windows Python matrix. Public deployment is not claimed.
- The archived v1 seed-7301 Oracle source is failed diagnostic evidence, not a
  partial campaign pass. Its persona-RNG replay divergence and SQLite sidecars
  were corrected and verified by the preceding replay-integrity revision.
- The archived v2 seed-7311 source and replay reached tick 335, including the
  first arrival, and verified as `exact: true` with `differences: []`, but
  receipt generation exposed the total-row versus
  living-population census bug. The immutable evidence is not reused.
- V3 seed 7321 is excluded diagnostic evidence. Its original failed receipt
  records the pre-inspection source hash, but diagnosis later write-opened the
  local source artifact; it is not admissible and is never reused.
- V4 seeds 7331 and 7332 have eligible exact source/replay receipts but remain
  diagnostic and are never reused. Seed 7333's exact pair failed receipt
  eligibility at tick 125 because the runtime mislabeled a government-treasury
  execution failure as a retryable planner rejection; the receipt correctly
  excluded that forecast, run, and fixed corpus.
- V5 seeds 7341–7347 have eligible exact source/replay receipts but remain
  diagnostic. Seed 7348's finalized source exposed ambiguous duplicate-event
  citations during replay; four articles failed closed and nine information
  tables diverged. Seeds 7349–7350 were never run. The seven receipt-bound
  replay databases and fourteen Oracle source/replay receipts belong only to
  seeds 7341–7347; seed 7348 has no eligible replay database or Oracle
  source/replay receipt. Final corrected offline replay
  `replay-oracle-calibration-v5-s7348-5220b912ae` reached tick 335 with
  `exact: true`, identical logical hash `fee77b65…b378`, all 82 deterministic
  tables exact, and `differences: []`; it remains post-source diagnostic proof.
  Completed cleanup removed 320 v5 source-checkpoint database bodies, 160
  fixed-code replay checkpoint bodies, four derived fixed-replay final
  databases, and the superseded partial seed-7343 replay: 485 database files and
  `111.945217 GiB` total. Retained artifacts are all authoritative final sources;
  the seven eligible replay databases and fourteen source/replay receipts for
  seeds 7341–7347; all source-checkpoint manifests/hashes, claims, and reports;
  the 160 fixed-code replay checkpoint manifests; and the ignored compact final
  exact receipt. Seed 7348 remains excluded and has no eligible source/replay
  receipt or retained replay database. No v5 artifact enters a later corpus.
- V6 seed 7351 stopped at tick 65 after a successful Kimi answer returned
  `confidence: "medium"` instead of the strict `low|med|high` value. Runtime
  persisted a rule rejection, an `insufficient_data` prediction, and a missed
  checkpoint. Spend was $0.18351, with no provider, budget, or tool-execution
  failure. V6 is preserved and excluded; seeds 7352–7360 were never run, and no
  v6 artifact enters a later corpus.
- V7 seeds 7361–7364 each retain passed, eligible source receipts and exact
  335-tick companion replays with zero differences, but the campaign is
  archived and incomplete. Seed 7365 is paused at tick 335 in `FINALIZE`; its
  immutable standalone database has SHA-256
  `b48b0c5a02270f6b09eafb5c32c8480a44f42057289048faedde9474d8ca8ce5`,
  no sidecars, 32,114 calls, 12 Oracle calls, six resolved forecasts/checkpoints,
  balanced USD, and `$0.2754108` spend. Receipt production measured 13,658 ms
  scheduled E2E against a 13,660 ms governed-call sum. The common producer now
  clamps continuous and resumed durations to the conservatively rounded call
  sum, but seed 7365's commit/tree-bound claim prevents post-fix resume or an
  eligible receipt. It has no replay or receipt, seeds 7366–7370 were never run,
  and no aggregate V7 manifest or receipt exists. No V7 artifact or seed is
  reused in V8.
- V7 archive cleanup removed exactly the 200 source checkpoint database bodies
  matching `^oracle-calibration-v7-s736[1-5]_t\d+\.db$`, reclaiming
  49,647,239,168 bytes (`46.237595 GiB`), while retaining the complete
  manifest/hash inventory and all final evidence.
- V8 seeds 7371–7374 retain passed, eligible source receipts and exact tick-335
  companion replays. Seed 7375 stopped at tick 245 after Kimi returned a
  billing-cycle usage-limit failure; its persisted `provider_failure` excludes
  the arm and the immutable ten-run V8 corpus. It is never resumed, substituted,
  or pooled into V9; seeds 7376–7380 were never run.
- V8 source-body cleanup removed exactly 189 checkpoint databases matching
  `^oracle-calibration-v8-s737[1-5]_t\d+\.db$` (40 each for seeds
  7371–7374 and 29 for seed 7375), totaling 43,999,223,808 bytes. Retain five
  sources, four replays, 189 source manifests, 160 replay manifests, five
  claims, five initialized markers, eight source/replay receipts, reports, and
  configurations. No source/replay checkpoint body or SQLite sidecar remains;
  all nine retained final databases pass immutable read-only `quick_check`, and
  eligible source/replay hashes match their receipts.
- The current precommitted V9 explicit-manifest Oracle latency/calibration
  campaign uses fresh seeds 7381–7390, odd control/even rumor arms, and only the
  Oracle live through `minimax/MiniMax-M3`. Standard ≤512k pricing is pinned
  at $0.30/M input, $1.20/M output, and $0.06/M cached input with
  `provider_automatic` caching and a $25 per-run cap. Commitment SHA-256 is
  `8a1845ebe9e916b8618a1c17170dc8a2b439c929ea1e1118670e21683c341a8e`.
  V9, the 30-day rumor gate, and the 365-day/$200 acceptance run require
  separate execution and evidence. The
  Oracle campaign cannot pass below ten eligible runs, 60 resolved forecasts,
  both outcomes, p90 under 60 seconds, Brier under 0.25, and exact replay of
  every finalized source. No V9 live evidence is claimed yet. Engine semantics
  7 and database schema 11 remain unchanged.
- PR #20 implementation is authorized for squash merge after the reconciled
  local gate. Do not tag, publish, or deploy publicly until the live gates and a
  fresh provenance/license/dependency/secret audit pass under separate
  authorization.
- Generated databases and reports corroborate findings but do not outrank
  committed code, tests, or locally resolvable provenance.
- A provider cache miss is telemetry, not a simulation failure; missing required
  recorded responses or dangling provenance is a replay failure.

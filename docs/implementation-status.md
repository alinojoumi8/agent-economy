# Agent Economy — Implementation Status & PRD Gap Assessment

> **Assessment date:** 2026-07-14
>
> **Code baseline:** `main` at merge commit
> `255555c2b24530c0bd39aed2f501277a468adc0a`
>
> **Database / maintained engine contract:** schema v11 / semantics 7
>
> **Release state:** PR #15 is merged. Its exact-head matrix and post-merge CI
> run `29368193807` passed all five jobs. Tagging and publication remain separate
> actions.

## Executive verdict

The PRD-v1 P0/P1 feature surfaces and the R18 participant, R19 1,000-agent,
R20 regional, and R21 real-U.S. calibration extensions are implemented. The semantics-7 closure completes
the remaining code contracts for bank loss recognition, retirement liquidity,
deterministic arrival/persona handling, autonomous regional trade/migration,
portable recorded replay, provider cache modes, and additive memory ranking.

The full local gate, five-tick closure rehearsal, bounded MiniMax pilot, and
historical/semantics-7 exact replays are complete. The live run spent
`$0.01121124` under its `$1` cap, all 42 proposals were accepted, and
privacy/provenance checks found zero defects. PR #15 merged to `main` as
`255555c2b24530c0bd39aed2f501277a468adc0a` after its exact-head dashboard and
Ubuntu/Windows Python 3.11/3.12 matrix passed. Post-merge CI run `29368193807`
repeated all five jobs successfully.

## Semantics-7 closure matrix

| Surface | Implemented contract | Repository evidence | Final evidence state |
|---|---|---|---|
| Versioning | Maintained profiles select semantics 7; markerless and stored semantics 1–6 retain historical behavior; explicit forks may opt in; schema remains v11. Unsupported future semantics and schemas now fail closed. | [Base profile](../runs/base.yaml), [v2 profile](../runs/v2.yaml), replay compatibility tests | **Passed:** 86 initial focused, 93 final adversarial, 280-test closure, and 303-test post-merge cleanup gates |
| Bank defaults | Eligible collateral is seized first. Only unrecovered principal is posted from the bank's currency-matched equity account to `SYS_LOSS` through balanced `loan_loss_chargeoff`; the existing default event reports recovered and net charged-off cents. | [Credit engine](../engine/credit.py), [semantics-7 credit tests](../tests/test_credit_semantics7.py) | **Passed:** live 120,000 NSD default, 5,000 recovery, 115,000 net charge-off |
| Retirement | `withdraw_savings{amount}` is retiree-only and moves funds between the actor's own declared, same-currency savings/checking accounts. Config `retirement_liquidity_target_cents` becomes public `retirement_drawdown_target_cents` beside `savings_balance`; pre-consumption drawdown, no job search, retired cadence, and stronger conversation participation are semantics-7-only. | [Action executor](../engine/actions.py), [lifecycle](../engine/lifecycle.py), [retirement tests](../tests/test_retirement_semantics7.py) | **Passed:** five targeted live withdrawals; no rejected proposals |
| Arrivals and personas | Due arrivals spawn deterministically during `NIGHT_CLOSE`, use visible population inflow and a 70/30 checking/savings split, then receive exactly one governed `role=persona,purpose=persona` call before their first morning decision. Enrichment is bounded; malformed success falls back deterministically; provider/budget pauses resume; missing recorded replay responses fail closed. | [Owned persona wrapper](../agents/personas/library.py), [world loop](../world/loop.py), [arrival tests](../tests/test_arrival_personas.py) | **Passed:** exact 70/30 live split, one enriched persona call, zero provenance defects |
| R20 autonomy | Regional context exposes bounded FX/wallet facts, at most five executable trade opportunities, and career-gated migration options. Trade requires an effective cross-region contract, inventory, and importer funds and is invoiced in the importer's currency. Migration requires a healthy unemployed non-retiree, wage threshold, authorization, and no disqualifying credit exposure. | [Region engine](../engine/regions.py), [regional tests](../tests/test_v2_regions.py) | **Passed:** 399,999 IVC shipment delivered tick 3; migration completed tick 2 |
| Replay fixture | Physical LLM row IDs canonicalize through deterministic referenced-call content; missing/dangling/wrong logical references fail. Recorded sources open read-only without migration or lingering locks. Completed/missed acceptance orchestration effects replay exactly. Fixture v2 strips raw provider envelopes, uses `repo://` paths, and restores recorded dataset/calibration/scenario inputs instead of current manifests. | [Verifier](../world/replay_verify.py), [portable fixture test](../tests/test_recorded_replay_golden.py), [source lifecycle tests](../tests/test_replay_source_lifecycle.py), [acceptance tests](../tests/test_acceptance.py) | **Passed:** semantics-5 fixture artifact `af57eed5…952d7`, normalized replay `2efcabed…f9170`, semantics-7 replays exact, source hash/schema unchanged |
| Prompt caching | `prompt_cache_mode` supports `off`, `provider_automatic`, `openai_key`, and `anthropic_ephemeral`; adapter/mode mismatches fail readiness; legacy `prompt_cache_key` aliases keyed OpenAI mode; cached-token billing is retained. | [Adapters](../llm/adapters.py), [readiness](../llm/readiness.py), [cache tests](../tests/test_prompt_caching.py) | **Passed:** 10,974/20,782 cached input tokens; all 21 MiniMax calls marked cached |
| Memory ranking | Retrieval uses the authoritative weighted sum `0.5·recency_decay + 0.3·importance + 0.2·relevance`, with a regression that distinguishes it from multiplication. | [Memory](../agents/memory.py), [ranking test](../tests/test_memory_ranking.py) | **Passed:** focused and full regression gates |
| Closure profiles | Paired five-tick profiles seed a near-defaulted loan, retiree, due arrival, qualified shipment, and migration opportunity. The live profile routes persona/selected strategic work to MiniMax, keeps background behavior scripted, and caps spend at `$1`. | [Rehearsal](../runs/v2-spec-closure-rehearsal.yaml), [live pilot](../runs/v2-spec-closure-live.yaml), [fixture seeder](../world/spec_closure_fixture.py) | **Passed:** `5a0d40d773` and `b4832032ba`, both exact offline replay |

## Current extension status

| Requirement | Disposition | Current status | Remaining boundary |
|---|---|---|---|
| **R18 — Participant mode** | Implemented extension | One controlled citizen uses the normal action validator/ledger with durable queued/executed/rejected/cancelled history and replay-safe provenance. | Participant-influenced runs remain disqualified from observer-only acceptance. |
| **R19 — 1,000-agent scale** | Implemented extension | Deterministic core/periphery population, promotion/demotion, regional genesis, conserved balances, replay, observatory, and recorded performance gate exist. | Downstream release hardware should publish its own benchmark. |
| **R20 — Regions, trade, migration, FX** | Implemented extension | Multicurrency ledgers, regional markets, FX inventory, shipments, migration, API/UI/report/replay surfaces, and semantics-7 autonomous opportunity context are implemented. | Five-tick rehearsal/live gates and exact replay passed. |
| **R21 — Real-data calibration** | Implemented extension | Explicit `real_us` mode deterministically samples pinned 2022 SCF income, liquid-holding, and total-net-worth records plus 2022 SUSB employer-firm classes, records per-draw provenance and distance evidence, and replays from recorded targets without a manifest. | `LIQ` funds deposits; SCF total net worth is an engine-owned off-ledger calibration baseline visible in the inspector. Identities stay fictional and default mode stays synthetic. |
| **R22 — Hosted multi-user service** | Deferred | Local single-process observatory only; no auth, tenancy, hosted persistence, or tenant isolation. | Separate architecture, security, operations, and load-test project. |

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

## Current semantics-7 run evidence

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

## PRD-v1 acceptance boundary

All P0/P1 code surfaces remain implemented. Four release-quality proof areas are
still operational rather than missing code:

1. the corrected 30-day live rumor gate;
2. representative Oracle p50/p90 latency and a resolved calibration corpus;
3. the explicitly authorized 365-day/$200 live acceptance campaign; and
4. a fresh release-candidate provenance/license/dependency/secret audit before
   tagging or publication.

The five-tick semantics-7 pilot supplements those gates; it does not replace
them. R21's SCF/SUSB supports are pinned; unrelated optional sources remain
separate.

## Semantics-7 verification snapshot

| Check | Result |
|---|---|
| Checkpoint baseline | Existing six-feature work was checkpointed after **231 Python tests**, **16 dashboard tests**, dashboard build, and `git diff --check` passed. |
| Focused semantics-7 tests | **Passed:** 86 tests across credit, retirement, arrival/persona, R20, replay, cache, memory ranking, pause/resume, and portability; then 93 integrated adversarial tests after final fixes. |
| Full Python / data | **Passed:** semantics-7 closure 280 tests in 165.73 seconds; post-merge compatibility/replay cleanup 303 tests in 178.22 seconds; R21 integrated gate 328 tests in 140.24 seconds; compileall green; FRED/BLS/SCF/SUSB fixtures verified. |
| Dashboard / hygiene | **Passed:** 16 tests; npm audit 0; license notice check; 599-module build byte-identical twice; static bundle fresh; clean diff. |
| Portable `fd0adc5dc1` fixture | **Passed:** sanitized v2 artifact restored/replayed offline with networking prohibited under stored semantics 5 and normalized hash `2efcabed…f9170`. |
| Free closure rehearsal | **Passed:** `5a0d40d773`, all targets, six checkpoints, balanced currencies, exact replay. |
| Bounded live pilot | **Passed:** MiniMax ready; `b4832032ba`, `$0.01121124`, all 42 proposals accepted, zero provider/privacy/provenance failures. |
| Live offline replay | **Passed:** `replay-b4832032ba-8d99c25c56`, tick/hash identical, `differences: []`. |
| R21 recorded replay | **Passed:** `24d8dc242e` sampled 70 households and 12 realized firms through tick 5 with zero reconciliation failures; `replay-24d8dc242e-a9ed4f2910` matched hash `95b4b8bd…0cee369a`. |
| CI / PR | **Passed:** PR #15 exact-head and post-merge dashboard plus Ubuntu/Windows Python 3.11/3.12 matrices; merge `255555c2`, post-merge run `29368193807`. |

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
- R21 real-U.S. calibration is implemented; R22 hosted multi-user operation
  remains outstanding.
- The 30-day rumor gate, Oracle latency/calibration campaign, and 365-day/$200
  acceptance run require separate execution and evidence.
- Generated databases and reports corroborate findings but do not outrank
  committed code, tests, or locally resolvable provenance.
- A provider cache miss is telemetry, not a simulation failure; missing required
  recorded responses or dangling provenance is a replay failure.

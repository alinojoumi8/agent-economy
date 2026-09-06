# Agent Economy model description

Model-description ID: **agent-economy-odd-v1**. Written 2026-09-06 against the
Semantics 1–14 implementation. This describes implemented mechanisms, including
opt-ins, rather than asserting that every profile enables them. The
[implementation-status ledger](../implementation-status.md) remains authoritative
for release maturity. Study manifests should retain this version and the exact
code/configuration identity.

The organization follows the purpose, entities/scales, scheduling, design
concepts, initialization, inputs and submodel categories of
[ODD](https://www.jasss.org/23/2/7.html). The mechanism descriptions below come
from this repository.

## Purpose and fitness

The model investigates interactions between bounded agent decisions,
information, balance sheets and institutional rules in a fictional economy.
Useful questions include model-conditional bank-run propagation, goods-price
adjustment, trading under different information policies, and comparisons of
decision policies under identical settlement rules.

Accounting consistency, replay reproducibility and empirical realism are
separate claims. Passing the ledger/replay gates does not establish a realistic
price process, demographic transition or policy prediction. Initial real-data
calibration does not validate later dynamics. A study must name the question,
relevant submodels, excluded mechanisms and validation patterns.

## Entities, state and scales

| Entity | Implemented state and constraint | Source |
|---|---|---|
| Citizen/agent | Stable ID, age, alive/retired status, accounts, work, preferences, beliefs and memories; configured core/periphery policy | [Agents](../../agents), [lifecycle](../../engine/lifecycle.py) |
| Family/dependents | Legacy dependent count influences demand; births currently increment a count. Separate persistent child/household membership is pending | [Lifecycle](../../engine/lifecycle.py), [planned S4–S5](../plans/2026-09-06-research-city-specs.md) |
| Firms | Cash account, employees, product/posted price, inventory, loans, shares, entry/exit and optional startup/legal state | [Firms](../../engine/firms.py), [startups](../../engine/startups.py) |
| Banks and central bank | Reserves, equity, deposits, loan claims, underwriting, liquidity support and policy decisions | [Banking and credit](../../engine/credit.py) |
| Labor, equity and FX markets | Employment/contracts, price-time ordered equity orders and executions, optional regional currencies/FX | [Labor](../../engine/labor.py), [exchange](../../engine/exchange.py), [regions](../../engine/regions.py) |
| Government/institutions | Profile-dependent fiscal, health, legal, political and civic tasks | [Engine](../../engine), [architecture](../architecture.md) |
| Places/construction | Semantics 12 civic places/presence and Semantics 13 project/permit/funding/work completion contracts | [City](../../engine/city.py), [construction](../../engine/construction.py) |

One world tick is a simulated day. Accounting uses integer minor currency units
(cents for the maintained currencies). Wages, interest, production, aging and
decisions follow their own schedules within that clock; a display animation
does not consume a simulated day. A multi-decade demographic study must actually
cover that horizon. Daily equity settlement cannot support intraday latency or
high-frequency trading claims.

Coordinates describe the model's geography or explicitly derived layout. The
city records daily presence slots; straight paths between them are a display
interpolation, not measured travel or economic transport.

## Scheduling and authority

[World.step](../../world/loop.py) runs deterministic phases for night close,
optional inbox delivery, decisions, action execution, market clearing,
newsroom, evening communication, memory and finalization. The exact phase
contract depends on the stored semantics version. Night close orders financial
and institutional sweeps, production, lifecycle and shocks. Changing that order
can change outcomes and requires versioned semantics.

Agents propose structured actions. [Action execution](../../engine/actions.py)
checks identity, role, ownership, balances and domain rules. Monetary effects
pass through [the ledger](../../engine/ledger.py); rejected proposals are not
economic events. Final boundaries reconcile and persist phase/RNG state.
Provider interruption pauses visibly. It is not a silent substitute-policy arm.

## Design concepts and behavior

| Mechanism class | Examples | Interpretation |
|---|---|---|
| Accounting constraint | Balanced integer ledger legs, ownership transfer, resource revalidation | An identity enforced by code, not an estimated behavioral law |
| Externally specified process | Initial wealth/productivity, hazard parameters, shock timing and institutional rules | Assumptions to vary or calibrate |
| Scripted/adaptive policy | State-dependent consumption, pricing, hiring, borrowing and order decisions | A testable baseline; outcomes are partly consequences of these rules |
| Recorded LLM decision | Role-scoped perceptions, structured proposals, bounded belief changes | Conditional on model, prompt, information, cadence and provider behavior |
| Visual derivation | Layout, crowd separation and interpolated movement | Explanation/navigation; no economic authority |

Agents have bounded information and do not share one omniscient prompt. Core
agents use their configured gateway; peripheral agents can use local policies
without a provider call. Both face the same economic validator. Memories,
communication exposure and belief updates shape later decisions. Communication
authorization and historical projections must exclude future/private facts.

Aggregate fluctuations may emerge from these interactions, but an interesting
trajectory does not by itself establish emergence independent of scripting.
Use ablations of policies, information, shocks and institutional regimes.
Record all failures and negative results as well as successful worlds.

## Initialization, inputs and randomness

[Genesis](../../world/genesis.py) creates the configured population, banks,
firms, endowments and relationships. Synthetic initialization is maintained;
[R21 calibration](../../research/r21.py) optionally samples pinned real-data
targets and records provenance. Scenario packs and dataset manifests identify
input versions/checksums. Offline replay restores source-owned input rows and
recorded decisions without re-reading a changed external manifest.

Current semantics use seeded engine/persona streams. Equal seeds and equal
initial canonical state do not guarantee equal later exogenous draws if an arm
changes the number of draws. Independent mechanism/entity keyed streams remain
a future versioned extension. The research runner records excluded shock and
scenario descriptors separately from its common-state digest.

## Economic submodels and limitations

Goods production currently combines workforce/productivity, inventory and
externally priced system inputs. Consumption settles posted prices subject to
inventory and cash. Existing successful-sale events do not record all intended,
unaffordable or rationed demand. Supplier networks, capital depreciation and
materials-backed construction need additional physical-stock contracts.

The equity exchange matches orders by price/time and settles cash/shares.
Initial price requires an execution. A secondary share sale transfers cash
between owners; it is not new financing of the firm or GDP. Known redemption
values belong to laboratory benchmarks. A real firm's latent fundamental value
is not observed truth. Total-return interpretation needs explicit corporate
actions and dividend treatment.

Current loans are funded from bank reserves. This is not a general commercial
bank deposit-creation model. Any new banking regime must separately reconcile
claims, liabilities, reserves, capital, default and settlement, and must be
identified in the study contract.

Legacy births increase dependent counts, death can select a social heir, and
replacement arrivals are sampled adults with external endowments. Adult study
actions exchange resources for skill gains in opt-in cognition profiles.
Persistent child identities, households, capacity-constrained schools and
education-to-work transitions are pending extensions. Legacy arrival housing
charges are not evidence of a discovered rental market.

## Observation and validation

[The metric registry](../../research/metric_registry.py) distinguishes units,
currency policies, populations, windows, price kinds and missingness. Its strict
reader preserves original engine values, refuses unsupported definitions and
unconverted mixed-currency aggregates, and reads share prices from actual trades
with execution age. The legacy `cpi` is a posted-price index; the legacy equity
index weights last prices by share count and is not a total-return index.

[Research attempts](../../research/attempts.py) separate execution status from
eligibility, preserve source/replay artifacts and verify their receipts.
[Analysis](../../research/analysis.py) uses complete eligible world/seed pairs,
reports exclusions and missing outcomes, and bootstraps pairs. The legacy
runners produce exploratory model-conditional evidence; a statistical floor
of two pairs is not a power calculation or confirmatory protocol.

Required evidence grows with the question: known-answer accounting/market
fixtures; replay and reconciliation; sensitivity across seeds and policies;
separate calibration and holdout data; realistic demographic horizons; then
bounded cost/fidelity and scale studies. The
[execution roadmap](../plans/2026-09-06-research-city-roadmap.md) records the
remaining benchmark, interface and economic extensions.

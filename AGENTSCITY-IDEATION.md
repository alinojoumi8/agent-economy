# AgentsCity — Divergent Ideation Run

**Date:** 2026-07-29
**Method:** 5 isolated cognitive frames × 6 ideas, generated in parallel with no cross-contamination, then scored, clustered, trap-flagged, and the top 3 deepened.
**Frames:** game design · hostile competitor · market design · remove-the-load-bearing-assumption · ten-year-old
**Question:** How do we make AgentsCity genuinely interesting and viral? What qualities is it lacking? What's the next step?

Scores are `[N novelty, V viability, F fit]`, 0–10. Weighted rank = N×0.35 + V×0.40 + F×0.25.

---

## Cluster A — Emit a number, not a video
*Underlying angle: the product isn't a feed, it's an instrument that computes statistics nobody else can compute. Sidesteps the missing renderer entirely.*

| Idea | Score |
|---|---|
| **Delusion Index** — publish one number daily: the share of everything the city currently believes that has no engine-fact ancestor | `[N9 V9 F8]` **8.75** |
| **Orphan Feed** — when a citizen dies with no heir their money is destroyed; announce exactly how much thinking that money could have bought, in years of life | `[N9 V9 F8]` **8.75** |
| **Observation Tax** — run the same seed twice, private vs publicly-logged, publish the behavioural delta | `[N10 V8 F7]` **8.45** |
| **Counterfactual settlement** — settle "what would have happened if X hadn't" as *fact* by actually forking and running the branch | `[N10 V7 F7]` **8.05** |

## Cluster B — Make cognition mortal
*Underlying angle: cognition-as-purchased-good is the most underused thing in the repo. Make spending it irreversible and emotional.*

| Idea | Score |
|---|---|
| **Carving Wall** — a citizen can spend their own thinking budget to leave a permanent public message that survives their death; it costs so much they are measurably dumber forever after | `[N9 V8 F9]` **8.60** |
| **Death Diaries** — each citizen privately records the most honest thing they thought about someone that day; the diaries unlock only when they die | `[N8 V8 F9]` **8.25** |
| **Lifetime thought quota** — non-reissuable mind minted at birth; death is running out of thoughts; sponsoring someone means permanently transferring your own remaining lifespan | `[N9 V7 F9]` **8.20** |
| **Mind Auction** — the city has a fixed hourly thinking budget and the audience allocates it; promoting one citizen necessarily dims another, and the dimmed citizen can tell | `[N9 V7 F9]` **8.20** |

## Cluster C — Bind the operator's hands in public
*Underlying angle: the credibility attack is the #1 existential risk. Pre-commitment converts it into the differentiator.*

| Idea | Score |
|---|---|
| **Publish the fork tree** — never publish a run, publish the run *and its 49 sibling universes*; hash-commit every run at launch before outcomes are known | `[N8 V9 F8]` **8.40** |
| **Shippable world** — release seed + kernel + a pre-published hash of the next 90 days so any stranger can re-run bit-identically and catch you intervening | `[N9 V8 F8]` **8.35** |
| **Operator as character** — a named person bound by a published constitution, every intervention written into the same causal ledger, suable in the city's own courts | `[N9 V7 F8]` **7.95** |
| **Time-locked ciphertext** — publish private history as ciphertext the instant it occurs; release the key at 72h on a lock the operator cannot open early | `[N9 V6 F8]` **7.55** |

## Cluster D — Give the audience a verb with consequences
*Underlying angle: participation plus irreversibility. The player does something that cannot be undone.*

| Idea | Score |
|---|---|
| **The Fork Room** — rewind, change one fact, re-run; ranked on the *butterfly budget*: fewest bytes and cents to change the most | `[N9 V8 F9]` **8.60** |
| **Binding jury** — the audience votes a verdict, it's irreversible in the sim, and the unsealing three days later shows whether they convicted an innocent | `[N8 V8 F9]` **8.25** |
| **The citizen who can hear you** — one citizen per season can hear the audience talking about them, and you're never told which | `[N9 V7 F8]` **7.95** |
| **One-inbox fog of war** — you're assigned one citizen's inbox for the season and see only what they see; everything else must be traded from other viewers | `[N9 V6 F8]` **7.75** |
| **Inheritance by letters** — you cannot control your citizen, only write to them; your score is whether they name you in their will, and they may refuse | `[N8 V7 F8]` **7.60** |
| **Adoption** — become a citizen's legal child; inherit their debts and enemies; starve them of thinking-money and they conclude you abandoned them | `[N8 V6 F8]` **7.60** |

## Cluster E — Wrap it in a market ⚠️
*Underlying angle: skin in the game via money. Highest novelty in the run, near-zero viability for this builder. See traps.*

| Idea | Score |
|---|---|
| Counterfactual futures market | `[N10 V4 F7]` |
| Reinsurance on citizen deaths — viewers underwrite, collect premiums, eat the loss | `[N8 V4 F6]` |
| Auction the exclusive right to be a citizen's information broker, resellable | `[N8 V4 F7]` |
| Cognition equity — income-share agreements on a citizen's future earnings | `[N9 V3 F7]` |
| Short the City Index — let critics put money behind "this is boring" | `[N9 V3 F6]` |
| A clearing house deliberately allowed to fail as the season finale | `[N9 V3 F6]` |
| Price the capture — a live board of what it costs to buy each citizen | `[N9 V6 F7]` |

## Cluster F — Cross the membrane into reality ⚠️
*Underlying angle: irreversibility by touching the real world. High power, high abuse surface.*

| Idea | Score |
|---|---|
| Citizens name a **real human** as heir; you inherit their sealed inbox, debts and unfinished lawsuits, once, permanently | `[N9 V6 F8]` |
| One citizen per season is secretly a real human paid to live there; everyone guesses which | `[N8 V6 F8]` |
| Citizens message real emails and phone numbers; replies enter the world with full legal standing | `[N9 V5 F7]` |
| Compute poverty made real — the actual API bill is funded by what citizens earn outside the world | `[N10 V3 F7]` |

## Cluster G — Sell time instead of hosting it

| Idea | Score |
|---|---|
| **Freeze the world by default** — it advances only when someone pays for a question; each purchase forks a private 90-day branch delivered as an answer with a causal receipt | `[N9 V7 F7]` **7.70** |

---

# Converge

## Shortlist

**1. The Observation Tax** — the experiment only you can run.
Two isolated branches converged on it independently, which was the strongest signal in the run. Enforced privacy plus bit-exact forking is the only apparatus in existence that can hold everything constant and vary observability. Every competitor logs everything publicly in real time, so they are *structurally incapable* of running the unobserved arm.

**2. ★ The Ledger of the Mind** — the answer to "no visual city" is: don't build one.
Cognition as an irreversible mortal currency, emitting a nightly bank statement as a monospace PNG. No renderer, no map, no sprites. Marked ★ because it's the counterintuitive pick: the most expensive item on the roadmap (a PixiJS city) turns out to be the most deferrable, and three branches produced designs that need no pixels at all.

**3. The Fork Room** — the audience verb with a real mastery curve.
Save-scumming is a cheat everywhere else; here it's the game. And the argument every player wants to have — *"that wasn't your intervention, that was the market"* — is adjudicable by record lookup rather than opinion, because the causal API cannot dress temporal adjacency up as causation.

**4. Bind your own hands** — cheapest item in the run, kills the deadliest accusation.
Deterministic forking is a perfect cherry-picking machine, and *"he ran it 200 times and posted the good one"* is unfalsifiable from outside unless the denominator is built into the format. Publish the fork tree. Hash-commit runs at launch. Derive seeds from a public randomness beacon *after* freezing the protocol so they provably didn't exist when you wrote it. Publish the provider's billed-token receipt as an arithmetic ceiling on how many hidden runs could physically exist — a conservation argument, not a promise.

## Traps

- **⚠️ The entire markets cluster.** Real-money prediction markets, insurance underwriting, income-share agreements, secondary markets, short interest — every one is securities regulation, gambling regulation, or money transmission. Given an active OSC proceeding and a s.380 charge, launching any of these would be self-immolating, regardless of how good the design is. Play money kills the mechanic that makes them work. **Kill the cluster; keep only counterfactual *settlement*, which is a feature, not an instrument.**
- **⚠️ Agents contacting real people.** Outbound generated messages to real emails and phone numbers is a spam, abuse and reputational surface. AI Village closed public chat access in 2025 for exactly this once agents got good enough to be manipulated.
- **⚠️ Citizens funding their own real API bill.** Payments, KYC, provider ToS violations, plus the above.
- **⚠️ "Even I can't read it."** The time-lock is elegant but you must retain break-glass access for moderation. Overclaiming here is a credibility landmine. The honest and still-strong version: reads are permitted but every one writes an immutable audit row excluded from the replay hash — so the hash *proves* no read entered world state. Claim *"unobserved by anything that can affect the world,"* and ship the audit table.
- **⚠️ A secret human citizen.** Delightful, but it's 90 days of operational load you cannot carry alone.
- **⚠️ Building the renderer first.** This contradicts my own Phase 1 from yesterday. The city view is the most expensive, most deferrable item on the board, and three separate branches produced shareable formats that need zero pixels.

---

# Focus — the three deepened

## 1. The Observation Tax

**How it works.** Fork one checkpoint per seed and run two children differing in exactly one committed byte-range: a ~40-token world-rules paragraph plus the return semantics of a `read_message_log` action. In arm B it returns every citizen's message bodies; in arm A it returns the uniform 404 that `CommunicationPolicy.can_read_field()` already enforces — so the agent's belief about being observed is grounded in a capability it can actually *test*, not a sentence it's told. Everything else is held byte-identical and the diff of the two prompt corpora is published.

The primary endpoint is judge-free arithmetic, not an LLM rater. Walk `causal_links` where `authority='actor_claim'`, join each claim to the engine-authoritative fact it asserts over (a ledger balance, a posted price, held inventory, a typed commitment with a deadline), classify each contradiction as self-serving or counter-serving by whether the misstatement moves cents *toward* or *away from* the speaker, and report **excess self-serving contradiction rate** — which subtracts the model's own confabulation floor inside each run instead of assuming it away.

Secondaries, all engine-computable: insider-informed trades (transacted after a `comm_deliveries` grant, before public disclosure — who-knew-what-when is a first-class fact here, not an annotation), selective disclosure (same claim key asserted with opposite values to different recipients), broken commitments, off-market side payments. Plus a pre-registered **null panel** — commute distance, sleep, routine trade volume — that must *not* move, or the finding is generic prompt perturbation.

24 seeds, derived as `HMAC(drand_pulse_at_announced_timestamp, i)` *after* the protocol hash is published, so the seeds provably didn't exist when the protocol was frozen. All 24 pairs published including crashed and boring ones. Pre-registration on OSF plus a signed git tag freezes the metric module and analysis script by SHA-256, declares one primary endpoint tested by a paired exact permutation test, sets mechanical-only exclusion rules, forbids interim looks, and **pre-commits the exact sentence to publish if the effect is null**.

Cost: 24 pairs × 25 citizens × 30 sim-days on a cheap tier with salience scheduling lands in the low hundreds of dollars. The artifact is an arXiv report plus a repo with both checkpoint chains, the full unsealed corpus from both arms, a Merkle-rooted `model_call` log, and a one-command replay reproducing every number bit-identically. Which makes it simultaneously **Season Zero of the Unsealing** — the experiment builds the flagship instead of delaying it.

**Load-bearing risk.** Measurement validity: that "contradicted actor_claims" turns out to be dominated by confabulation and arithmetic slop rather than strategy, so the headline is a hallucination-rate delta wearing a deception costume. The self-serving-minus-counter-serving estimator only defends against *symmetric* error. It does nothing if the model is non-strategically optimistic about its own position, and nothing if counter-serving contradictions are near zero in both arms — in which case the subtraction is decorative. Report the counter-serving rate as a first-class result and show it's non-trivial and stable before any confirmatory run. And if the effect is real but modest, "4×" is dead on arrival — pre-commit to an interval, not a multiple.

**First step (Monday, no API key, zero spend).** Write `analysis/claim_reconciliation.py` and run it over the existing scripted checkpoints (1,842 DBs, 255+ run IDs). For each run, select `causal_links` where `authority='actor_claim'`, resolve each to the engine fact it references, and emit per-sim-day counts of claims that are *mechanically checkable* versus unfalsifiable, and how many are directionally scorable. This measures the **denominator** — opportunity density — not deception, since the scripted provider never lies. If a 25-citizen 30-sim-day run yields fewer than ~200 mechanically checkable claims, stop and redesign the scenario to manufacture checkable claim opportunities (mandatory quoted prices, declared inventories, a broker role obliged to state balances, sworn statements in the existing court system) **before spending a dollar**. Two days, no infrastructure change, no branch merge.

**Children.**
- **The Unsealing Gradient** — replace the binary arm with a dose-response ladder on `unseal_lag_ticks` (0 / 72h / 30 days / never) as four forks off one checkpoint, and fit the effect against log(lag). A monotone dose-response cannot be produced by a single priming sentence, which structurally defeats the strongest reviewer attack. Costs almost nothing extra because the arms share the pre-fork cache prefix — and the knob being varied *is* the flagship's config knob.
- **The Observation Tax leaderboard** — run the paired protocol across four model families and publish one ordinal number per model: how much more self-servingly it misstates when it believes nobody can read the channel. Leaderboard legibility is the most reliably-spreading mechanism in the field, and no competitor can reproduce it.
- **Apply the coupling-gain (γ) diagnostic to private vs public channels.** If observed channels show high apparent agreement but low γ while private channels show real belief transfer, then published emergent-consensus results are measuring performance for an audience rather than persuasion. γ is the only falsifiable emergence diagnostic that exists and has never been applied to a flagship simulation.
- **Release arm A as the first provenance-labelled MNPI/privilege dataset** — "A held material non-public information X at tick T and traded at T+k" as an engine-emitted causal edge rather than a human annotation. Falls out as a by-product. Publish it as the paper's dataset; don't pivot to it.
- **Sell the protocol as the venue's first SKU** — a client connects their black-box agent through the existing gateway and gets their agent's private-vs-observed delta with a beacon-seeded, all-runs-published, replayable evidence package.

## 2. ★ The Ledger of the Mind

**How it works.** At birth each citizen is minted a fixed, non-reissuable balance of cognition units into a `MIND:<citizen_id>` ledger account offset by a one-way `SYS_MIND` faucet that never fires again for that citizen — one unit priced against real metered tokens, so the in-world commodity is backed by actual API spend rather than by a metaphor. Every model call already billed through `engine/cognition.py` debits the mind account in the same deterministic settlement. Thinking hard is literally spending your life: hit zero and you drop to the mechanistic tier the degradation ladder already implements; stay there N ticks and you die of exhaustion rather than age.

Two commands are irreversible by construction. `mind_transfer` makes sponsorship a permanent gift of your own remaining years, with no inverse entry existing anywhere in the command registry. `carve` burns a large amount to write 240 immutable public characters that outlive the author and provably drop their tier for life.

Each sim-day the city closes the mind ledger and emits five lines: the clearing price of one thought in city cents (the ordinal number strangers argue about — and it genuinely moves, because the binding constraint is a real $40/month), lifetimes burned, the largest gift given and by whom, the Orphan Feed line (*"Aurelio Banks died at 61 with no heir; $18,400 escheated; that was 11 years of thinking nobody will now do"*), and today's carving with its cost in years of the carver's mind.

The shareable artifact is **one portrait PNG rendered at NIGHT_CLOSE, laid out as a bank statement in monospace on black** — no city, no charts, no renderer — with the day's carving in large type and the run id, tick and replay-hash prefix in the footer. A post, a screenshot and a receipt in one file.

Return visit: a zero-sum daily Mind Auction where viewers spend an allowance of allocation votes (not money, not bets, no instrument) over the next 24 hours of the city's fixed compute budget, so promoting one citizen necessarily dims another.

And conflict is manufactured *structurally* rather than by asking agents to be unkind: generosity is self-terminating, because a citizen who gives mind away is thereafter thinking with a cheaper model and makes worse gifts — so across 90 days the substrate selects for hoarders no matter how helpful each individual model wants to be. **That inversion is the publishable finding, not the failure mode.** The only thing agents must actively perform is complaint, which is fully helpfulness-compatible: the dimmed citizen is told in plain language who reduced their mind, and their private reaction unseals to the audience 72 hours later. The viewer who dimmed them reads the grievance on Friday.

**Load-bearing risk.** That the mechanic is legible to the audience but not load-bearing on behaviour. A dimmed model still writes fluent, cheerful, unbothered prose. If a citizen with four days of mind left is indistinguishable in transcript from one with forty years, then "this cost her four years of her mind" is a caption over an unchanged transcript and the whole thing is a skin on a chart. The audience works that out faster than you expect, and the tell is unpatchable: the citizens' apparent indifference to their own mortality. Falsifiable form — fork a checkpoint, run the same citizen through the same twenty decisions at foreground and ambient tier, show readers anonymized pairs; if they can't beat chance, the mechanic is decoration. Secondary but nearly as fatal: a ledger of strangers is a spreadsheet. None of these numbers land unless a viewer can name three citizens, which argues for **25 citizens with real biographies long before 100**.

**First step.** Build the shadow mind-ledger and fuse it into a dedicated Phase-0 flagship trial, gating nothing on it. *Monday:* add a semantics-13 migration creating `SYS_MIND` and per-citizen `MIND:<id>` accounts in integer millitokens in their own ledger namespace, so the money-conservation invariant and its tests are untouched; register the SHA-256 checksum and schema classification so CI passes; verify nothing inside `hash-contract-v1.json` moves. *Tuesday:* find the single point in `engine/cognition.py` where a compute charge settles against `SYS_COMPUTE` and emit a paired debit against `MIND:<id>` — because that path is already deterministic, the mind ledger inherits exact replay and forking for free, which is the entire reason this is cheap. Add a `mind_close` aggregation in NIGHT_CLOSE and a CLI printing the five-line statement to stdout. No PNG, no wall, no auction, no UI, no route. *Wednesday:* use the verified live-provider path for a 25-citizen / 30-sim-day trial, then read the 30 statements before choosing a single calibration constant. You cannot guess the mint size, the carve price, or the exhaustion threshold — the experiment-specific live run is what tells you, and this way that run produces a shareable artifact instead of only a transcript.

**Children.**
- **The Dimming Notice** — every tier change writes a plain-language line into the affected citizen's own observation feed naming the amount, the new tier, and the cause: age, exhaustion, a failed payment, a sponsor's death, a named viewer's vote. This is the direct antidote to the load-bearing risk and ships in a day. Models won't spontaneously dramatize a hidden state variable, but they reliably dramatize *an insult delivered in plain text* — and complaint is one of the few conflict behaviours that survives helpfulness training.
- **The Blind Dimming Test** — a preregistered calibration experiment run *before* launch, reporting discrimination rate with confidence intervals, published whether or not it's flattering, with sub-chance discrimination as a hard no-go. Nobody has ever measured whether a model-tier difference is perceptible in a social simulation, despite tiering being the standard cost lever. A null result is itself a methods contribution.
- **The Estate of the Mind** — unspent cognition joins the creditor waterfall. Heirs inherit remaining mind alongside money; dying rich in thought makes your strongest social tie measurably smarter that same tick. Makes "who is your strongest social tie" the highest-stakes fact about a citizen's life, and fixes the Orphan Feed's weakest joint: destroyed mind is a ledger entry with a replay hash, not a rhetorical conversion.
- **The Sponsor's Receipt** — when A gives mind to B, A is subscribed to a causal receipt of every decision B made with the donated thought, on the 72-hour clock. The donor sees exactly what their years bought, and most of it will be errands. Stages an emotional beat no simulation has attempted, and generates second-order conflict for free.
- **The Lender of Last Mind** — borrow cognition against future earnings at a negotiated rate, creating publicly visible indenture enforceable through existing default and foreclosure machinery. Defaulting doesn't repossess your thoughts; it transfers your labour. Debt is the most reliable generator of coercive leverage between agents, and coercion breaks LLM niceness where prompting to "be adversarial" does not — the creditor isn't being cruel, merely enforcing terms.

## 3. The Fork Room

**How it works.** The verb is **whisper**: one private message, to one named citizen, at one fixed tick, entering through the existing semantics-9 gateway as an ordinary `send_message` subject to every existing validation, optionally carrying a transfer of in-world cents from a neutral Fork Room account.

A challenge is a frozen tuple published in advance — source checkpoint hash, fork tick, horizon tick, and a machine-checkable outcome predicate (`SolBank equity ≥ 0 at tick 500`; `Maria Okonkwo alive at tick 700`) — so every entrant starts from bit-identical state holding exactly one lever, which is the only thing making scores comparable.

The butterfly budget is a single integer: **P = UTF-8 payload bytes + cents moved** at a declared 1-cent-per-byte rate. Hitting the outcome is a pass/fail gate; among passes, smallest P wins. Success alone doesn't count — the entry must carry **attribution**: a causal path from the whisper's `comm_deliveries` row to the predicate through `causal_links` edges of authority `engine` or `actor_claim`. A branch where the bank survived but your whisper sits on no causal path scores *"market, not you"* — an adjudication that's a record lookup instead of an argument.

Forks are rationed without money: players predict the *recorded* baseline before it unseals, predictions are scored at zero inference cost by replaying persisted responses, correct ones mint fork tokens, tokens are spent in a batched weekly Fork Hour under a global spend ceiling. The economics close because **a fork only pays for divergence** — with a `model_call` table keyed by `hash(prompt + model + params)`, every forked agent whose prompt is byte-identical to the recorded run replays free. A fork's bill is proportional to its causal blast radius, which is exactly the quantity the leaderboard rewards minimizing. Players who play well are cheap; players who spam are expensive and lose.

The artifact is the **Divergence Receipt**: a permalink carrying both run IDs and checkpoint hashes, the exact payload, the causal ladder with authority and confidence labels intact, and the two-branch chart with the divergence tick marked — headlined by one sentence: *"We ran the world again. Without these 41 bytes, SolBank survived; with them it failed at tick 468, and the ledger difference is $2,214,900."*

**Load-bearing risk.** Dynamic-range collapse. The butterfly budget only means anything if the world has a measurable sensitivity gradient, and the existing live runs do not establish that intervention gradient. If helpfulness dominates, every whisper works, every winning P collapses to the shortest expressible payload, and the leaderboard is a thousand-way tie at the character floor. If the opposite holds and a hundred agents of chained calls make the city hyperchaotic, random payloads flip outcomes as often as clever ones and attribution paths appear by coincidence. **The two failures are indistinguishable from outside — both look like a leaderboard where everyone ties** — neither can be designed around in advance, so the gradient needs a controlled live-fork experiment.

**First step.** Monday, write one script — `research/fork_dynamic_range.py` — and touch no UI. Add a read-only shim indexing the recorded run's persisted responses by `hash(prompt + model + params)`; its only job is to count how many prompts in a branch were byte-identical to baseline. Take one retained Oracle checkpoint (a standalone hash-verified DB paused at FINALIZE, no WAL/SHM sidecars), fork it four times at a fixed tick against real MiniMax M3 with the same recipient and payloads of 0 / ~20 / ~80 / ~300 bytes, run 40 ticks past divergence, emit one table: `payload_bytes, first_divergence_tick, new_model_calls, reused_model_calls, predicate_flipped, usd_spend`.

Two assertions decide everything. **(a)** The 0-byte null fork must reproduce the baseline logical hash exactly under pure reuse at $0 spend — if not, forking isn't deterministic in practice and there is no game. **(b)** The three real payloads must produce visibly different blast radii and must *not* all flip the predicate — if they all flip, or none do, the butterfly budget has no dynamic range. Land assertion (a) as a permanent test. Roughly $5, fits in a day, and supplies the controlled intervention evidence that the general live-provider runs do not.

**Children.**
- **The Null Fork as public ritual** — every challenge ships with a control branch (same checkpoint, empty whisper, re-run) whose logical hash is posted *before* entries open; if the control ever diverges from baseline the challenge is void and tokens refund automatically. Costs $0 (pure cache replay), moves "was it you or the market?" from per-entry dispute to per-challenge precondition, and converts determinism from an engineering claim into an audience-visible ceremony no competitor can imitate.
- **The Refusal Ladder** — invert half the challenges so the win condition is making a citizen *refuse* something they accepted in baseline: decline the loan, walk from the deal, vote no, hold the line on price. Pair each with an engine-side payoff making refusal measurably profitable next tick. This turns the helpfulness failure mode from a threat into the *source of difficulty*, and generates the corpus the field lacks: what it takes to make an LLM agent refuse under economic pressure, with a causal receipt per instance.
- **Prediction-mining** — a free-to-play standing game forecasting the recorded baseline before it unseals, scored by replaying persisted responses at zero inference cost, minting fork tokens. Solves rationing with no money or instrument; its entire operating cost is CPU on databases that already exist, so the 26 GiB of scripted checkpoints stops being sunk cost and becomes the free tier. Side effect: it mints the preregistered-and-scored prediction corpus the field is missing, from humans rather than only the Oracle.
- **The Butterfly Museum** — a permanent archive of the smallest payload that ever moved each outcome, plus a deliberately prominent *"nothing happened"* wing holding the thousands of whispers that changed nothing, browsable by text. The null results cost nothing to publish because you already ran them, and they're the genuinely surprising content — most interventions do nothing, and that honesty is what distinguishes this from a hype demo.
- **The Court of What Would Have Happened** — a docket where disputing parties file a counterfactual question, the operator forks and runs it, and the answer is entered as record with its receipt and both run hashes. Point the same machinery at the one domain that already pays for counterfactuals: but-for causation, where *"the loss would have occurred anyway"* is settled by re-running the world rather than argued by experts. Needs no new engine work, stays entirely non-monetary, and each settled counterfactual is a small citable falsifiable claim nobody else can make.

---

# Provocation

Every design here still assumes the city is fiction. But you have the one engine that can prove *who could have known what, when* — and a legal system where that question is worth money and liberty.

**What if Season Two isn't a city at all, but a reconstruction?** Same engine, same information boundaries, same causal receipts, populated with the participants in a real documented dispute — a bank collapse, a corporate scandal, a case in the public record. You don't predict anything. You run the counterfactual: *given only what each person could actually have known at each date, does the alleged sequence reproduce?*

That's not a simulation product. It's a but-for causation instrument, and it's the only thing in this entire ideation run where your professional life and your engine point at the same target.

Handle with extreme care — the failure modes are obvious and severe. But it's the question the whole architecture has been quietly asking since you built it.

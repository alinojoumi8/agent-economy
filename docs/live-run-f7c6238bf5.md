# Live run `f7c6238bf5`: diagnostic record

## Disposition

Run `f7c6238bf5` is a preserved diagnostic pilot, not v1 acceptance evidence. It is paused at tick 76 and must not be resumed as the final production run because it predates the research-validity changes and failed the rumor gate.

## What the run proved

- The 100-agent MiniMax/Kimi population ran through tick 76 with an exactly conserved ledger.
- The database contains 15,913 recorded LLM calls and no provider, contract, or reconciliation failure event.
- Recorded spend was `$24.23293715`.
- The Oracle completed one scored answer in 28,480 ms. This is useful route evidence, but one sample cannot establish p90.
- Policy-rate and oil-shock traces passed the original evaluator before the run was stopped.

## What failed

The rumor reached the intended 40-agent audience and six qualifying conversations occurred, but the old evaluator observed the required trust drop for only 7 of 40 agents and no deposits moved. The corrected evaluator now fails this legacy run closed because it has no append-only `belief_updated` history from which to establish each exposed agent's true pre-rumor baseline.

The run also exposed three confounds:

- citizen prompts included exact bank reserve ratios;
- reserved beliefs could overwrite history and leave their intended ranges;
- the reported GDP proxy added wages to final-goods sales, creating payday spikes inconsistent with its label.

## Corrective path

New semantics-v3 profiles use public bank status for citizens, persist bounded belief updates with provenance, target the current depositors of the largest bank, measure relative trust loss from actual history, separate final-goods GDP from labor income, and require a distinct `$200` efficiency gate plus at least five Oracle latency samples.

The next paid step is the separately authorized, capped 30-day profile at [`runs/acceptance/pilot.yaml`](../runs/acceptance/pilot.yaml). A fresh 365-day production acceptance run should start only after that pilot passes.

# Causal phenomena evidence — offline functional prototype

**Evidence date:** 2026-07-10

**Acceptance boundary:** implemented and tested with deterministic scripted agents;
real MiniMax/Kimi confirmation remains unproven.

The PRD calls a phenomenon emergent when the engine does not directly map a cause
to its macro consequence. In each chain below, the engine exposes state and
validates an action, while an agent policy chooses the consequential action.

## 1. Credibility shock → deposit flight

**Causal chain:** rumor memory → lower bank-trust belief → agent-selected
`move_deposits` action → cross-bank reserve settlement → lower deposits and
reserve ratio.

**Metric signature:** across five matched seeds, the rumor arm averaged 16.8
deposit moves versus 0 in controls, Bank 1 deposits ended 811,181.606 cents lower,
and its reserve ratio ended 0.4869 lower. See
[`rumor-vs-control.md`](experiments/rumor-vs-control.md).

**Why it is not an engine shortcut:** the rumor hook writes information to
memories but never moves money. Money moves only after an agent returns a
validated `move_deposits` action.

**Automated evidence:** `test_rumor_propagation_moves_beliefs_and_deposits` and
the five-seed experiment-harness acceptance test.

## 2. Oil shock → firm repricing

**Causal chain:** oil shock doubles the commodity index → the founder observes a
higher unit cost → the founder chooses `set_price` → the validator applies the
new goods price.

**Metric signature:** the controlled proof changes the commodity index from
1.0 to 2.0. With a 180-cent base input cost, the founder's target price moves
from 288 to 576 cents and the resulting `price_set` event records the decision.

**Why it is not an engine shortcut:** the oil hook changes only the commodity
index. It does not edit a firm's product price; repricing requires a founder
decision through the normal action contract.

**Automated evidence:**
`test_oil_and_rate_shocks_produce_downstream_agent_decisions`.

## 3. Policy-rate shock → loan repricing

**Causal chain:** policy-rate shock changes the benchmark → a credit officer
observes the benchmark with the same borrower file → the officer chooses a
higher `rate_bps` in `approve_loan` → the bank originates at that quoted rate.

**Metric signature:** with the same application, moving the policy rate from 500
to 900 bps moves the agent's loan quote from 1,100 to 1,500 bps. The executed
loan stores 1,500 bps.

**Why it is not an engine shortcut:** the shock does not edit any loan. The
credit officer sets the quote; the engine only enforces bank policy guardrails
and double-entry settlement.

**Automated evidence:**
`test_oil_and_rate_shocks_produce_downstream_agent_decisions`.

## Production confirmation still required

These proofs establish the causal architecture and repeatable prototype
phenomena. Because the offline policies are deterministic substitutes for model
decisions, they do not by themselves satisfy the strongest reading of the PRD's
"not scripted" production success gate. Final production evidence must repeat
all three signatures with the locked MiniMax/Kimi routes and retain the run
databases, provider usage/cost logs, and generated reports.

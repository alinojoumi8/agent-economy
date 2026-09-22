# Direct JEV validation — 2026-09-22

Base: `a0ca62dac477552c20637f0c86f224510a3b7f8d` (remote main at validation).
The separate local `main` reference differs; it was not moved. Changes live on
`codex/jev-direct-typesafe`. No live world, server or Hermes process was operated.

## Bounded live compatibility comparison

The first four lexically ordered original A inputs from the frozen adjudication
experiment were selected before dispatch. Eight requests were planned, alternating
route order by case, with a separate $0.025 allowance per route and zero retries.
The operation stopped after request seven; request eight was never sent.

| Route | Successful validated answers | Matched-pair median | Input/output tokens, all reported calls | Accounted cost |
|---|---:|---:|---:|---:|
| Direct TypeSafe `jev-1.13.0` | 3/3 | 0.395580s | 14,178 / 1,502 | $0.000595476 |
| OpenRouter `typesafe/jev-1.13-20260917` | 3/4 | 0.406009s | 22,032 / 2,510 | $0.000925344 |

Direct cost is tariff-based; OpenRouter cost is provider-reported. The budget
ledgers retain nanodollar amounts; gateway display values may round slightly.
Total known accounted cost was $0.001520820, well below the $0.05 cap.

All three matched pairs selected the same action (`wait`); the first case also
selected the same fiscal ballot (`austerity`). Full answer objects differed,
including probability/confidence values. There were no observed timeouts. This
tiny partial sample does not establish superior reliability or speed, identical
weights, or the cause of the earlier interrupted experiment's timeout.

### Why request seven stopped

OpenRouter reported 7,866 input / 1,008 output tokens, against the comparison
harness's inherited generic 700-output-token reservation. The existing budget
guard stopped with:

`provider reported usage outside its reservation; study dispatch is stopped`

Six reservations settled; the seventh is recorded as `breached` with reason
`usage_exceeds_reservation`. No reservations are pending or unknown. This was a
per-request token declaration breach, not exhaustion of the dollar allowance.
The initial result receipt conservatively marked usage unknown for any exception;
inspection of the durable budget confirms usage and cost for this particular
failure are known. No retry or repair call was performed.

For future comparison invocations, the harness now explicitly declares 2,048
output tokens, matching the typed decision profile. The regression simulates the
observed 1,008-token response. The original partial comparison was not rerun,
rewritten, or mixed into the frozen memory-intervention experiment.

### Evidence

Local ignored directory: `reports/out/jev-direct-transport-20260922/`.
It contains the plan and copied inputs, original executed harness, attempt/result
receipts, isolated gateway/budget databases, summary, and input preservation
hashes. All four preserved input files match their before hashes.
The original executed harness SHA-256 is
`57714e2bcfa9630b3ca035dc6f81bb199ea08da582304d510423520eeb82df3a`.
Sensitive input/response content and databases are deliberately not committed.

## Offline checks

- JEV/direct contracts, gateway, budgets, replay and documentation: **290 passed**.
- Focused direct adapter/gateway/comparison tests: **36 passed**.
- Corrected comparison harness: **4 passed** (included in the focused suite).
- Dashboard: **284 passed**, build and license check passed. The build emits the
  existing large-chunk warning. No generated dashboard changes are included.
- Compilation, dependency consistency, dataset verification and diff checks passed.
- Python locked-dependency audit and npm audit: no known vulnerabilities reported.

The full Python suite was attempted, then stopped after an unrelated failure was
isolated. The failing assertion is
`tests/test_architecture_boundaries.py::test_removed_architecture_symbols_do_not_return`:
it expects `LocalCitizenshipService` to have no `repository` parameter, while the
base implementation has one. An isolated run of the first relevant files gave
**62 passed / 1 failed**; the same test failed independently on a clean detached
checkout of `a0ca62d`. The full suite is **not** claimed green.

Recommendation: direct access is compatible and available as an opt-in route.
Keep production defaults and the interrupted experiment unchanged. A larger
predeclared comparison is needed before claiming a reliability improvement.

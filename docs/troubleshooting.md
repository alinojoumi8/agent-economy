# Troubleshooting

## Provider preflight fails

Run the exact profile explicitly:

```powershell
python run.py --config runs/acceptance/production.yaml --preflight-live
```

Confirm that `MINIMAX_API_KEY` and `KIMI_API_KEY` exist in the environment and
that the reported catalogs contain `MiniMax-M3` and `kimi-for-coding`. Do not
print or commit credential values.

## The run says rate limited or overloaded

HTTP 429 and MiniMax HTTP 529 are waiting states, not failed ticks. Inspect
`rate_limit` in `/api/run/status` or the dashboard for the attempt count and
next retry. The fallback cooldown sequence is 15/30/60/120/300 seconds unless
the provider supplies `Retry-After`.

Pause or stop remains interruptible during cooldown. On restart, successful
responses from the active phase are reused and are not billed twice.

## The run paused for a provider failure

Non-overload failures are intentionally bounded. Preserve the database, fix or
wait out the provider issue, then resume with the original configuration and
run ID. Verify these invariants before continuing:

- completed `tick` did not advance;
- `active_tick` and `next_phase` identify the interrupted work;
- `COUNT(*) == COUNT(DISTINCT cache_key)` in `llm_calls`;
- ledger reconciliation still passes.

## The dashboard controls look stale

Refresh `/api/run/status`. It is authoritative for status, speed, active phase,
provider cooldown, and report path. Rebuild the committed bundle after changing
dashboard source:

```powershell
cd dashboard
npm test -- --run
npm run build
```

Acceptance evidence is heavier than ordinary run status. On a large database,
`/api/acceptance/status` can take seconds to refresh, but it runs off the server
event loop and is cached briefly so controls and WebSockets stay responsive.

## A database says `running` but no process exists

An operating-system kill or forced terminal termination can prevent Python's
`finally` cleanup from running. Confirm there is no matching simulation process
and no server holding the database, then preserve the file and change the run to
`paused` through an operator recovery procedure. Record an
`orphaned_run_recovered` event with the previous state, new state, and reason.

Normal Ctrl+C, dashboard Pause/Stop, provider interruption, and application
exceptions execute phase-aware cleanup automatically. Never mark a truly active
run paused from another process.

## A run is halted

Do not restart, step, change speed, stop, or inject shocks into a halted run.
Preserve the database and diagnostic events. Investigate reconciliation first;
fork a known-good checkpoint only when the source evidence has been retained.

## Exact replay fails

Use the original run ID and leave provider credentials irrelevant:

```powershell
python run.py --replay <RUN_ID>
```

Inspect the replay proof for the first differing canonical table. A missing
request-key response means the source run was incomplete or predates durable
request reuse; do not permit a network fallback.

## Acceptance evidence fails

Open the generated JSON receipt and inspect each failed gate. Common causes are
an unfinished horizon, unresolved Oracle predictions, absent reviewed phenomena
YAML, missing N=5 experiment evidence, or a shock effect occurring before its
shock. Regenerate with `--acceptance-report` only after the underlying evidence
exists; report regeneration cannot make a failed gate pass.

A legacy run without `belief_updated` history fails the rumor gate by design;
the evaluator will not assume a universal initial trust value. A single Oracle
sample also cannot satisfy the production p90 gate, even when its latency is
below the limit.

## I need per-call diagnostics

Normal INFO output reports run-level milestones, checkpoints, repairs, pauses,
and failures without printing one line for every successful agent call. Set
`AGENT_ECONOMY_LOG_LEVEL=DEBUG` to include successful request, replay-hit,
resume-hit, tick, and HTTP-start records. Prompts, responses, and credentials
remain outside operational logs.

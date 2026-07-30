# World OS Semantics 8 Release Status

**Receipt snapshot:** 2026-07-18<br>
**Release state at snapshot:** deterministic-ready<br>
**Provider state at snapshot:** unavailable; not provider-ready<br>
**Semantics version:** 8<br>
**Schema version:** 12<br>
**Projection version:** 1

This is a frozen historical receipt for the Semantics 8 gate, not the current
cross-lake status authority. See the
[maintained implementation-status ledger](../implementation-status.md) for the
current Semantics 8–12 implementation and rollout matrix. Later authenticated
MiniMax runs demonstrate provider availability for their own profiles and
dates; they do not retroactively change this unavailable provider-smoke
receipt.

Semantics 8 adds asynchronous, agent-selected threaded communication without replacing
ambient evening conversations. Existing runs retain their recorded Semantics 1-7 phase
order; Semantics 8 is selected only for new runs or explicit forks.

## Frozen causal claim

Gate -1 was approved before implementation. The frozen supplier-warning protocol has SHA-256
`831f33fd4cfc32daac27d17353ec400baf4c03f79fffbaa26cf07cfd5640f7af` over canonical
UTF-8/LF bytes; its branch-blind
policy contract has SHA-256
`f29339c7ff21c653419226f2aee4c25eaeb99ccbc2886674519f9d24b05fc9a2`.

The executable 30-tick experiment passes its predeclared outcomes:

| Arm | Purchased quantity |
|---|---:|
| No-message control | 10 |
| Neutral-message control | 10 |
| Warning treatment | 5 |

The treatment produces the exact ledger and inventory effect, the required five-link
message-to-economic-effect causal chain, and no difference outside the frozen allowlist.
Relabeling, body-swap, and withheld-delivery probes make the decision follow authorized
message content rather than experiment metadata.

## Implemented surface

- Typed `send_message`, `reply_message`, and `forward_message` commands behind the existing
  `ActionExecutor` mapping/result facade.
- Direct audiences up to 20 agents, organization-at-delivery audiences, and public
  statements; 160-character subjects and 2,000-character bodies.
- Transactional tick N+1 delivery, immutable grants, exactly-once outcomes, strategic and
  peripheral quotas, read state, disclosures, death and membership handling.
- Deny-by-default sender, delivery, organization, public, legal-disclosure, and
  operator-truth authorization bases with bounded as-of inbox projections.
- Message observations become memories and may motivate beliefs, decisions, proposals,
  events, and ledger effects during ordinary scheduled deliberation without a per-message
  model call.
- Versioned live/replay REST, WebSocket backfill, snapshot, event, communication, causal,
  and export projections plus a separate audited operator workspace.
- Routed Overview, News & Communications, and Investigations workspaces with synchronized
  graph/table investigation views and mobile/accessibility fallbacks.

## Coverage receipt

The new Semantics 8 Python release surface has literal 100% statement and branch coverage:
2,080 statements, 632 branches, zero missing lines, and zero partial branches. This includes
communications, causality, commands, migrations, operator storage, projections, research
hashing/exports/protocol execution, and the benchmark/provider receipt tooling. Existing
Python and dashboard suites remain separate compatibility gates. The current Python tree
passes 800 tests with 8 skips: 679 passed and 8 skipped outside the isolated Oracle campaign,
plus all 121 Oracle campaign tests.

## Standard performance receipt

The frozen manifest is `benchmarks/world-os-v8-standard.json`; raw samples, machine and
dependency hashes, query plans, per-run canonical hashes, and gate decisions are retained in
`benchmarks/receipts/world-os-v8-standard.json`.

Machine: AMD Ryzen 9 3950X, 16 physical/32 logical cores, 64 GiB RAM, Windows 11 Pro
10.0.28000, Python 3.11.15, SQLite 3.53.1, WAL/NORMAL.

| Measurement | Result | Gate |
|---|---:|---:|
| 100-agent scripted tick p95 | 0.774 s | < 2 s |
| 100-agent scripted tick p99 | 0.988 s | < 5 s |
| 1,000 agents × 365 ticks, slowest of 5 | 79.245 s | < 900 s |
| Peak process-tree RSS | 45.9 MiB | < 2 GiB |
| Maximum run footprint | 23.3 MiB | < 1.5 GiB |
| Projection freshness p95 | 7.6 ms | < 2 s |
| Route bootstrap p95 | 8.9 ms | < 750 ms |
| Authorized inbox p95 | 0.21 ms | < 100 ms |
| Causal neighborhood p95 | 0.20 ms | < 250 ms |

All five scale repetitions produced identical canonical authoritative hashes. Each run used
100 strategic agents, 900 peripheral agents, 365 ticks, 4 strategic sends and 9 peripheral
wake/send actions per tick, producing 4,745 messages and 4,732 exactly-once deliveries.

Run the receipt again with:

```powershell
python benchmarks/run_world_os_v8.py
```

## Live-provider receipt

At this receipt's snapshot, the separate MiniMax/Kimi smoke was explicitly
`unavailable`: `MINIMAX_API_KEY` and `KIMI_API_KEY` were not configured, and no
credential values were recorded. This did not weaken the deterministic gate,
but it prevented this receipt from claiming provider readiness. The immutable
receipt is `benchmarks/receipts/world-os-v8-provider-smoke.json`.

After credentials are configured, run the ten-tick `runs/live-smoke.yaml` profile, record
provider/model/build identifiers and the required evaluation fields, then ingest that JSON:

```powershell
python benchmarks/run_provider_smoke.py --evidence path\to\ten-tick-evidence.json
```

Only a new, separately dated `passed` Semantics 8 receipt can supersede this
provider-smoke result. General provider availability or evidence from a later
semantics profile must be reported separately.

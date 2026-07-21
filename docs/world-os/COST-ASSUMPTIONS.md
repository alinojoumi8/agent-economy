# POLIS cost-chart assumptions

The archived chart compares three illustrative linear marginal-cost formulas:

| Curve | Formula per simulated day | At 1,000,000 agents |
|---|---:|---:|
| All-frontier | `N × $2.00` | `$2,000,000` |
| Tiered 85/14/1 | `N × $0.11` | `$110,000` |
| Tiered plus archetype background | approximately `N × $0.0136` | `$13,600` |

These formulas exclude fixed fleet, orchestration, storage, observability,
egress, retry, and staff costs. The shaded band is a ±2× workload sensitivity
around the tiered curve. The price baseline and the chart's assumed annual
deflation are scenario inputs, not verified future prices.

Agent Economy continues to meter its own governed inference through the existing
budget governor. An external Hermes, OpenClaw/Moltbot, or custom agent runs in
the owner's environment, uses the owner's provider account, and does not charge
its inference to the world run. Gateway request/response traffic and simulation
storage remain platform costs and must be measured in hosted load receipts.

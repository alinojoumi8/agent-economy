# Live Provider Validation

> **Historical scope:** This report validates the Kimi Code compatibility profile
> (`runs/production-kimi-code.yaml`). Kimi is currently disabled from the active
> production runtime; the K2.6 target remains in the opt-in
> `runs/production-k2.6.yaml` acceptance profile.

> **Assessment date:** 2026-07-10
>
> **Code baseline:** `b2b25c0` on `fix/provider-live-readiness`

## Active MiniMax-only validation

Kimi is disabled from the active `runs/production.yaml` profile. A fresh bounded
run on 2026-07-10 authenticated the MiniMax Token Plan model catalog and then
completed one real simulation tick:

| Check | Result |
|---|---|
| Run | `3f168fc2ff`, tick 1 |
| Provider/model | `minimax` / `MiniMax-M3` only |
| Recorded LLM calls | 55 |
| Kimi calls | 0 |
| Provider failures or pauses | 0 |
| Recorded cost | $0.035041 |
| Conversation diversity | 20/20 messages distinct |

The visible development server at `http://127.0.0.1:8321/` was restarted from
this run. Its readiness endpoint reports only the `minimax` routed provider.
>
> **Validated run:** `3478260d9e`, seed `42`, tick `1`
>
> **Credential handling:** key values and raw credentials are not recorded in this document, Git, reports, or logs.

## Result

The development simulation is healthy with the user's two subscription services:

- MiniMax Token Plan key (`sk-cp-*` family): `https://api.minimax.io/v1`, model `MiniMax-M3`.
- Kimi Code membership key (`sk-kimi-*` family): `https://api.kimi.com/coding/v1`, stable model alias `kimi-for-coding`. The alias currently serves K2.7 Code when Thinking is enabled.

Both authenticated `/models` checks passed. MiniMax returned eight available models and confirmed `MiniMax-M3`; Kimi returned two and confirmed `kimi-for-coding`. The endpoints and identifiers match the [MiniMax Token Plan](https://platform.minimax.io/subscribe/token-plan), [MiniMax M3](https://www.minimax.io/models/text/m3), and [Kimi Code API](https://www.kimi.com/code/docs/en/) documentation.

## Issues found and fixed

1. **Wrong Kimi service.** The Kimi Code key was being sent to the Moonshot pay-as-you-go endpoint and returned HTTP 401. The profile now uses the Kimi Code endpoint and stable model alias.
2. **Wrong Kimi sampling value.** K2.7 Code rejected `temperature: 0.7`; the provider requires `1.0`.
3. **Reasoning output truncation.** The original 700-token ceiling could end before either model emitted its JSON envelope. Production requests now allow up to 4,096 completion tokens.
4. **Token Plan concurrency and timeouts.** Eight concurrent calls and a 60-second timeout produced MiniMax timeouts. The profile now uses three concurrent calls and 180-second provider timeouts.
5. **Missing conversation and memory contracts.** Raw context was previously sent without an output schema, causing universal repair and empty persisted messages/summaries. Explicit schemas and gateway schema validation now cover both paths.
6. **Ambiguous identifiers.** Human-readable labels such as `firm7` caused invalid integer IDs. Prompts now expose prices/jobs as JSON and explicitly require context-provided integer IDs.
7. **False-success CLI output.** A provider pause could still print `done` and exit successfully. Headless runs now generate their report, print the pause reason, and exit nonzero.
8. **Quota waste after failure.** Outstanding concurrent tasks are cancelled after the first critical failure.
9. **Live replay ordering.** Network completion order changed non-semantic SQLite IDs. Memory/belief writes are now applied deterministically, and replay compares concurrency-owned tables by canonical logical rows.
10. **Opaque HTTP failures.** OpenAI-compatible provider errors now include a bounded response detail without logging request headers or credentials.

## Successful fresh run evidence

| Check | Result |
|---|---|
| Population | 100 agents, 14 firms, 2 banks |
| Tick | Fresh genesis through tick 1 |
| Logical LLM calls | 170 |
| MiniMax M3 | 163 calls; p50 33.249 s; p90 126.238 s |
| Kimi K2.7 Code | 7 calls; p50 14.582 s; p90 23.228 s |
| Provider failures / pauses | 0 / 0 |
| Final response contract failures | 0 |
| JSON repairs | 4 memory calls |
| Cached calls | MiniMax 161/163; Kimi 4/7 |
| Modeled equivalent usage cost | $0.112542 (subscription quota was used; this is the governor's price-equivalent accounting) |
| Conversations | 45 calls → 45 persisted messages |
| Daily summaries | 71 generated → 71 nonempty |
| Rejected actions | 11, all valid `out of stock` market outcomes |
| Ledger | Conserved; grand sum 0 cents; no account mismatches |
| Standalone report | `reports/out/run_3478260d9e_t1.html` generated locally |

The generated database and report are intentionally ignored by Git. This document records reproducible, secret-safe summary evidence; committed tests and code remain the primary proof.

## Browser live smoke after conversation and resume hardening

On 2026-07-10, run `19a2657e3e` exercised the compatibility profile through
the visible dashboard with a deliberately small 21-agent, 5-firm, 2-bank world:

| Check | Result |
|---|---|
| Completed ticks | 2, including Stop + report followed by Run and safe Pause |
| Total live calls | 62 |
| MiniMax M3 | 47 calls across decisions, founders, conversations, and memory |
| Kimi Code | 15 calls across institutional decisions, credit, VC, and Oracle |
| Oracle | Structured 15% bank-run forecast with four world-grounded drivers |
| Provider failures / pauses | 0 / 0 |
| Modeled equivalent usage cost | $0.090654 |
| Conversation diversity | 4/4 live messages distinct and context-specific |
| Browser console | No warnings or errors |

The Kimi response and model catalog both report `kimi-for-coding`. A Kimi Code
membership key does not expose or permit selecting `kimi-k2.6`; exact K2.6
validation still requires a separate Kimi API Platform credential.

## Exact replay

The CLI replay `replay-3478260d9e-a5a809d9f2` used stored responses only and matched all 27 deterministic tables:

- Source hash: `405b1d5ae37e58b7ab2c8a8baf6ac44a0c17ca134427a075e170fead4a9ce6c8`
- Replay hash: `405b1d5ae37e58b7ab2c8a8baf6ac44a0c17ca134427a075e170fead4a9ce6c8`
- Differences: none

## Verification

- `python -m pytest tests/ -q`: **69 passed in 77.02 seconds**.
- Python compile-all: passed.
- `git diff --check`: passed.
- Clean `npm ci` and Vite production build: passed.
- `npm audit --omit=dev`: zero vulnerabilities.
- Offline preflight and authenticated live model-catalog preflight: passed.

## Expansion boundary

This proves the local development runtime and one complete live tick. It does **not** prove the PRD's 365-day provider budget, Oracle-specific p90, or long-run rate-limit envelope.

The MiniMax documentation describes Token Plan as an individual/developer service and recommends pay-as-you-go for production workloads. Kimi distinguishes Kimi Code membership from its product/enterprise Platform API. Before hosted, multi-user, high-concurrency, or unattended long-run expansion, migrate to provider plans whose terms and rate limits cover that deployment pattern.

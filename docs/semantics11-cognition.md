# Semantics 11: live compute plans and learnable skills

Semantics 11 keeps three concerns separate:

- Skills are authoritative knowledge earned by a citizen.
- Compute subscriptions decide which model tier that citizen may use.
- Provider pools enforce live operational capacity, priority, timeout, cooldown,
  and failover.

The default desktop profile is `runs/evolving-live.yaml`. It requires all four
routed providers to pass a real JSON-contract preflight before genesis. There is
no scripted or mock inference fallback.

## Provider pools

| Lane | Capacity | Default work |
|---|---:|---|
| Ollama / `agent-economy-qwen3.5:9b-16k` | 2 | Local citizen plans |
| Ollama Cloud | 3 | GLM 5.1, Gemma 4, and Nemotron 3 Super cohorts |
| DeepSeek / `deepseek-v4-flash` | 6 | Flash plans and routine institutional work |
| MiniMax / `MiniMax-M3` | 2 | Premium VC and exchange decisions |
| Kimi / `kimi-for-coding` | 2 | Premium founder, policy, credit, legal, executive, and Oracle decisions |

The desktop-wide ceiling is 10. Policy and strategic requests have priority over
conversation, memory, and newsroom requests inside each lane. DeepSeek gets a
60-second provider timeout, local/premium lanes get 90 seconds, and Ollama Cloud
gets 120 seconds. Queueing, fallback, and provider time share a 240-second
logical-call deadline.

Each route has at most one live fallback: local to DeepSeek, Flash to local, and
premium to DeepSeek. HTTP 429 immediately places that provider in cooldown. If
both routes fail, the world checkpoints and pauses at the same phase without
settling the proposed action.

DeepSeek uses its OpenAI-compatible endpoint with JSON output and thinking
disabled. Ollama uses the OpenAI-compatible endpoint with `reasoning_effort:
none`, which keeps Qwen's response inside the JSON contract. The local alias
pins `num_ctx` to 16K; this avoids the large default context allocation while
retaining the same `qwen3.5:9b` weights.

## Citizen compute economy

At genesis, 65 non-institutional citizens receive exact seven-tick launch
grants: 33 local, 26 Flash, and six premium. The plans then renew only at
seven-tick boundaries:

- Local is free.
- Flash costs 5,000 cents.
- Premium costs 25,000 cents, requires level 3 in a non-household skill, and is
  capped at 20% of non-institutional citizens.

`buy_compute_plan`, `cancel_compute_plan`, and founder-only
`set_compute_sponsorship` changes are scheduled for tick N+1 and must coincide
with the current plan's expiry. Employer plans debit the firm's operating
account. Institutional plans debit the government treasury. Every charge credits
the balanced `sys:compute_service` account.

Routine legislators, lobbyists, reporters, editors, and government staff receive
Flash sponsorship. Strategic institutional roles receive premium sponsorship.
Premium agents still use DeepSeek Flash for conversation, memory, newsroom, and
report narration so scarce premium slots remain available for decisions.

`population_tier` controls wake cadence only. It never changes `model_tier` under
Semantics 11.

## Skills

Every agent has household finance, labor, commerce, entrepreneurship, finance,
law, media, and governance. Levels 0 through 5 use XP thresholds 0, 10, 30, 70,
140, and 250.

Accepted ordinary actions award 2 XP and accepted complex actions award 4 XP.
Rejected actions and `do_nothing` award none. `study_skill` is available on a
career-review day, consumes the entire action, costs 5,000 cents to
`sys:education_service`, and awards 10 XP. Each action/study history row records
the exact accepted `action_proposals.id`, making progression auditable rather
than inferred from same-tick activity.

The first release exposes skills to prompts and premium eligibility but does not
silently alter prices, ledger amounts, or action success probabilities.

## Persistence and observability

Schema 15 adds `agent_skills`, `agent_skill_history`,
`compute_subscriptions`, `llm_attempts`, and `runtime_tick_stats`. Skills and
subscriptions are deterministic world state. Attempt rows and simulated-day wall
times are operational evidence and are excluded from world hashing and exact
replay comparison. Final usable provider responses remain authoritative in
`llm_calls`.

`GET /api/llm/runtime` reports global and per-provider capacity, current and peak
occupancy, queue depth, p50/p95 queue and response latency, failures, rate limits,
fallbacks, cooldown, and p50/p95 simulated-day duration. The dashboard Overview
shows provider lanes; People shows each citizen's plan, payer, expiry, last route,
skills, XP, and progression history.

Every proposal and validation result remains in `action_proposals`; provider
attempts and accepted model calls remain in `llm_attempts` and `llm_calls`.
Operational JSON logs add phase/tick markers and five-second CPU, memory, and
provider-occupancy samples. They rotate at 10 MiB with five backups instead of
duplicating large prompts, responses, or action payloads. Three consecutive
resource-limit samples pause and checkpoint the run.

## Live launch

1. Copy `.env.example` to the ignored `.env` file and populate
   `DEEPSEEK_API_KEY`, `MINIMAX_API_KEY`, and `KIMI_API_KEY`.
2. Create the bounded-context Ollama alias:

   ```powershell
   ollama pull qwen3.5:9b
   ollama create agent-economy-qwen3.5:9b-16k -f deploy/ollama/Modelfile.qwen3.5-9b-16k
   ```

3. Run strict live preflight and launch:

```powershell
python run.py --config runs/evolving-live.yaml --preflight-live --serve --approve-live-inference
```

`--preflight-live` sends one real JSON-contract call through every provider. A
missing key, unavailable local model, invalid JSON contract, or failed health
check prevents genesis.

## Acceptance workflow

Inference tests use real providers. Provider-free tests are limited to schema,
math, routing selection, ledger, and deterministic state checks.

```powershell
# All-provider preflight, 10-lane concurrency, and real fault fallbacks.
python scripts/live_cognition_probe.py --config runs/evolving-live.yaml `
  --output reports/out/live_cognition_probe_full.json

# Fresh 100-agent, ten-day live source run.
python run.py --config runs/evolving-live.yaml --ticks 10 `
  --preflight-live --approve-live-inference

# Exact replay consumes the source's recorded llm_calls and makes no live calls.
python run.py --config runs/evolving-live.yaml --replay SOURCE_RUN_ID --ticks 10

# Persisted release receipt; exits non-zero if any gate fails.
python -m reports.cognition_acceptance SOURCE_RUN_ID `
  --probe reports/out/live_cognition_probe_full.json `
  --replay REPLAY_RUN_ID `
  --output reports/out/cognition_acceptance.json
```

The receipt requires all four providers, at least ten overlapping calls, median
day duration below three minutes, p95 below five minutes, the exact launch
distribution, exercised renewal/expiry/sponsorship/N+1 behavior, action-bound
skill history, balanced service accounts, no scripted/mock calls, complete spend
and failure telemetry, real timeout/rate-limit fallback evidence, and an exact
offline replay.

The DeepSeek adapter follows the official [API overview](https://api-docs.deepseek.com/),
[thinking-mode contract](https://api-docs.deepseek.com/guides/thinking_mode), and
[rate-limit behavior](https://api-docs.deepseek.com/quick_start/rate_limit).

# Configuration and providers

## Profile inheritance

Run profiles are YAML files. A profile can declare `extends`, resolved relative
to that profile, and override nested values from its base. The resolved
configuration and seed are persisted in `run_meta`, making each run auditable.

| Profile | Purpose | Credentials |
|---|---|---|
| `runs/base.yaml` | Offline deterministic development and tests | None |
| `runs/production.yaml` | Active 100-agent MiniMax M3 runtime | `MINIMAX_API_KEY` |
| `runs/production-k2.6.yaml` | Inactive locked PRD acceptance mix | MiniMax and Kimi Platform keys |
| `runs/production-kimi-code.yaml` | Inactive Kimi Code compatibility profile | MiniMax and Kimi Code membership keys |

Kimi profiles are explicit opt-ins. The runtime does not silently substitute a
provider, endpoint, model, or credential type.

## Environment variables

Secrets belong in the ignored `.env` file. Never put populated values in YAML,
documentation, tests, reports, commits, or issue text.

| Variable | Used by |
|---|---|
| `MINIMAX_API_KEY` | Active MiniMax M3 production profile and mixed profiles |
| `KIMI_API_KEY` | Explicit K2.6 Platform or Kimi Code profile only |
| `ANTHROPIC_API_KEY` | Optional custom Anthropic provider configuration |

Kimi Platform and Kimi Code credentials are different services. Platform K2.6
uses `https://api.moonshot.ai/v1`; Kimi Code membership uses
`https://api.kimi.com/coding/v1` and the `kimi-for-coding` alias.

## Important world settings

`runs/base.yaml` defines the full shape inherited by production profiles:

- `seed`: deterministic world and persona randomness.
- `population.size`: sampled citizens; institutional staff and healthcare
  founders are added during genesis.
- `banks`, `firms`, `exchange`, and `central_bank`: deterministic economy.
- `lifecycle`, `government`, `vc`, and `health`: P1 systems.
- `behavior` and `conversations`: decision cadence and social activity.
- `budget`: hard run cap, Oracle reserve, degradation thresholds, and initial
  conversation volume.
- `llm`: provider definitions, role/purpose routes, concurrency, and retries.
- `checkpoint_every`, `checkpoint_dir`, and `speed_delay_s`: operations.
- `outlets` and `shocks`: information economy and scheduled interventions.

Money values ending in `_cents` are integer cents. Rates ending in `_bps` are
basis points. One tick represents one simulated day.

## Agent population

The active production profile requests 87 sampled citizens. Genesis adds one
central banker, ten other institutional staff, and two healthcare founders for
exactly 100 agents. A custom profile's final count therefore depends on enabled
banks, outlets, government, and health institutions; inspect `/api/agents`
instead of assuming `population.size` is the total.

## LLM routing and failure policy

Every call passes through the gateway. Routing is based on role and purpose;
the active profile explicitly routes citizens, founders, conversations, memory,
institutional seats, and Oracle to MiniMax M3.

Before starting a real-provider run:

```powershell
python run.py --config <PROFILE> --preflight-live
```

A provider call is retried once. Continued failure records a diagnostic event,
reconciles and checkpoints the partial run, then pauses instead of falling back
to scripted behavior. Invalid structured output receives one repair call; both
provider calls are included in cost accounting.

## Budget governance

The default cap is $200 with a $10 Oracle reserve inside that cap. As world
spend crosses 60%, 80%, and 95% of its available budget, the governor reduces
conversation volume, stretches agent cadence, and finally limits calls to
institutional roles. At the cap, the run checkpoints and pauses cleanly.

Use a small explicit cap for experiments. Do not assume a subscription or token
plan makes provider calls free; the database stores modeled price-equivalent
cost for observability and acceptance evidence.

## Safe custom-profile workflow

1. Extend `runs/base.yaml` or the closest explicit profile.
2. Change only the settings required for the scenario.
3. Run static preflight, then live preflight if networking is enabled.
4. Start with a short headless run and inspect its report/database.
5. Preserve the profile alongside experiment results when reproducibility
   matters.

Never use a generated run database as stronger acceptance proof than committed
tests and code.

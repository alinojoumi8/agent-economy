# Configuration and providers

## Profile inheritance

Run profiles are YAML. `extends` is resolved relative to the current profile and
nested mappings are merged. The fully resolved configuration and seed are saved
in `run_meta`, so a database remains self-describing.

| Profile | Purpose | Network/cost |
|---|---|---|
| `runs/base.yaml` | Default offline development world | None |
| `runs/production.yaml` | Approx. 100-agent MiniMax/Kimi runtime | Live inference |
| `runs/acceptance/rehearsal.yaml` | Free 365-tick acceptance rehearsal | None |
| `runs/acceptance/pilot.yaml` | Bounded 30-tick rumor pilot | Live, capped at $25 |
| `runs/acceptance/production.yaml` | Full 365-tick acceptance | Live, uncapped policy plus $200 efficiency gate |
| `runs/experiments/rumor_vs_control.yaml` | Five-seed treatment/control study | None by default |
| `runs/r21-real-us.yaml` | Pinned SCF/SUSB calibrated genesis | None |

Profiles never silently change provider, model, endpoint, or credential type.

## Environment variables

Secrets belong in the ignored `.env` file or process environment.

| Variable | Purpose |
|---|---|
| `MINIMAX_API_KEY` | MiniMax Token Plan route in production profiles |
| `KIMI_API_KEY` | Kimi Code membership route in production profiles |
| `ANTHROPIC_API_KEY` | Optional custom Anthropic route |
| `AGENT_ECONOMY_LOG_LEVEL` | Python operational log threshold; default `INFO` |

Kimi Code membership keys use `https://api.kimi.com/coding/v1` and the
`kimi-for-coding` alias. They are not interchangeable with Moonshot platform
keys. Never put populated values in YAML, docs, reports, issues, or commits.

## Core world settings

| Key | Meaning |
|---|---|
| `seed` | World, persona, targeting, and lifecycle reproducibility |
| `engine_semantics_version` | Runtime compatibility contract; maintained profiles use `7` |
| `population.size` | Sampled citizen count; institutional/founder agents are added |
| `banks`, `firms`, `exchange` | Deterministic banking, production, and market parameters |
| `central_bank` | Policy target, neutral rate, and step bounds |
| `lifecycle`, `government`, `vc`, `health` | Optional P1 systems |
| `behavior`, `conversations` | Wake cadence, run threshold, and social volume |
| `checkpoint_every`, `checkpoint_dir` | Recovery cadence and storage |
| `speed_delay_s` | Wall-clock pause between ticks; does not change simulation time |
| `outlets`, `shocks` | Information institutions and scheduled interventions |

Money keys ending in `_cents` use integer cents. Rate keys ending in `_bps` use
basis points. One tick is one simulated day.

## R21 real-U.S. initialization

The default is `calibration.mode: synthetic`. Opt in only with pinned verified
supports:

```yaml
engine_semantics_version: 7
dataset_manifest: config/data-manifest.yaml
calibration:
  mode: real_us
  household_dataset_key: federal-reserve-scf
  firm_dataset_key: census-susb
  max_initial_firm_employees: 50
  minimum_wage_per_interval_cents: 50000
  maximum_wage_per_interval_cents: 5000000
```

Fresh runs verify and ingest the manifest before genesis. Replays ignore that
path and use the source run's recorded targets. `real_us` changes initialization
only: SCF income/work-status/liquid-holding/total-net-worth draws and SUSB
headcounts are applied to fictional personas and firms through dedicated
seed-derived PRNG streams. `LIQ` funds deposits; `NETWORTH` remains an
engine-owned off-ledger calibration baseline visible in agent provenance.
Missing supports, wrong adapter versions, malformed values, or non-verified
manifest rows fail closed.

## Information and beliefs

New production/base/acceptance profiles use:

```yaml
engine_semantics_version: 7
information:
  citizen_bank_visibility: public_status
beliefs:
  audit_history: true
  enforce_reserved_ranges: true
```

`citizen_bank_visibility` accepts:

- `public_status`: citizens/founders see bank name and public status only;
- `full_balance_sheet`: exposes reserve ratios and exists for intentional
  scenarios and legacy replay.

Reserved ranges are `trust:bank:*` `[0,1]`, `sentiment` `[-1,1]`, and
`inflation_expectation` `[-0.05,0.25]`. Finite out-of-range model output is
clamped and audited; non-finite output is rejected.

## Provider routing and failure policy

`runs/production.yaml` routes citizens/founders to `MiniMax-M3` and
institutional roles plus the Oracle to Kimi's `kimi-for-coding`. Conversation
and memory purposes inherit the agent's role route.

Every call passes through the gateway. Before a live run:

```powershell
python run.py --config runs/production.yaml --preflight-live
```

Readiness validates environment variables, endpoints, and model catalogs before
genesis. Rate limits/overload enter an interruptible provider-wide cooldown.
Other continuing failures use bounded retries, persist diagnostics, reconcile,
checkpoint the phase cursor, and pause. Invalid JSON receives one metered repair
attempt. There is no silent fallback to scripted behavior.

## Budget and acceptance settings

`budget.cap_usd` controls the runtime governor. Capped profiles degrade at
60/80/95% of their world budget by reducing conversations, stretching cadence,
and limiting calls to institutional roles, then pause at 100%. `null` disables
that hard cap while spend remains metered.

The `acceptance` block is evidence policy rather than call authorization:

- `min_ticks`, `min_agents`, `max_agents`;
- `max_spend_usd` and independent `efficiency_target_usd`;
- `oracle_p90_ms` and `oracle_min_latency_samples`;
- `oracle_questions` with exact scheduled ticks;
- optional `required_shocks`, `require_oracle_scoring`,
  `require_experiment`, and `require_phenomena` for bounded pilots.

Live acceptance additionally requires `--approve-live-inference` at the CLI.

## Rumor targeting

A research-valid rumor can resolve its target at fire time:

```yaml
params:
  bank_selector: largest_by_deposits
  audience: current_depositors
  n_agents: 40
```

`bank_selector` is `explicit` or `largest_by_deposits`; `audience` is
`all_citizens` or `current_depositors`. The `shock_fired` and `rumor` events
persist the resolved bank and exposed agent IDs without forcing beliefs or
withdrawals.

## Safe custom-profile workflow

1. Extend the closest maintained profile.
2. Change only scenario-relevant keys.
3. Run static and, if applicable, live preflight.
4. Start with a short headless run.
5. Inspect report, failure events, ledger reconciliation, and acceptance status.
6. Archive the resolved config, commit, seed, database, and evidence together.

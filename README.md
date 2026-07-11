# Agent Economy

[![CI](https://github.com/alinojoumi8/agent-economy/actions/workflows/ci.yml/badge.svg)](https://github.com/alinojoumi8/agent-economy/actions/workflows/ci.yml)

A living, miniature US-style economy populated by ~100 persona-driven agents —
teachers, founders, bankers, journalists — who work, trade, borrow, gossip, and
panic. **LLMs propose, a deterministic engine disposes**: every dollar flows
through a double-entry ledger that reconciles to zero every tick, so crashes and
bank runs are *real* within the sim. See [PRD.md](PRD.md) and
[TECH-SPEC.md](TECH-SPEC.md) for the full design.

## Quick start

```bash
pip install -r requirements.txt

# Offline deterministic observatory (world starts paused — press ▶ Run)
python run.py --config runs/base.yaml
# → http://127.0.0.1:8000

# Headless: run N ticks, emit an end-of-run report, exit
python run.py --config runs/base.yaml --ticks 30

# Resume a paused/checkpointed run; or prove an exact replay (no API cost)
python run.py --resume <RUN_ID>
python run.py --replay <RUN_ID>

# Report for any stored run
python run.py --report <RUN_ID>

# Tests (engine invariants, order book, lifecycle, governor, rumor pilot, determinism)
python -m pytest tests/ -q
```

## Development workflow

Work from a feature branch and open a pull request into `main`. GitHub Actions
runs the full test suite and compiles the Python sources on Windows and Linux
with Python 3.11 and 3.12. Dependabot checks Python and GitHub Actions
dependencies weekly.

Local API keys belong in `.env`, which is excluded from Git. Copy
`.env.example` when configuring the production provider profile; `runs/base.yaml`
remains fully offline and needs no key.

**No API key is needed for the explicit offline profile.** `runs/base.yaml` routes every role to the built-in
`scripted` provider — deterministic policy agents that shop, work, lend, reprice,
spread rumors, and run on banks. The whole system (dashboard, Oracle, shocks,
reports, replay) works offline and reproducibly. Same seed ⇒ identical event log.

Replay never mutates the source run. It creates a fresh `replay-*.db`, rebuilds
genesis, re-executes every tick against the source run's stored LLM responses,
and prints table-by-table SHA-256 proof. A missing response pauses the replay and
exits without contacting any live provider; a state mismatch exits with status 3.

The dashboard source lives in `dashboard/` and builds into `server/static/`.
For frontend development, run the FastAPI process on port 8000 and the Vite dev
server in a second terminal:

```bash
cd dashboard
npm ci
npm test
npm run dev
# production bundle: npm run build
```

Vite proxies `/api`, `/ws`, and `/reports` to FastAPI during development. The
production bundle is committed so normal Python users still start the complete
application with one command and no Node.js runtime.

## Operational logging

The Python process emits one JSON object per operational event to stderr, and
the dashboard emits the same style of secret-safe diagnostics to the browser
console. Stable event names cover CLI modes, server and HTTP/WebSocket lifecycle,
run controls, provider preflight/retry/repair/failure/cost outcomes, checkpoints,
safe pauses, reports, shocks, experiment arms, client fetch/action failures, and
malformed WebSocket data. Records include bounded context such as run ID, tick,
status, latency, path, and cost; prompts, responses, and credentials are not
logged, and credential-shaped fields or values are redacted. Set
`AGENT_ECONOMY_LOG_LEVEL=DEBUG` to include Python per-tick and request-start events.

These logs complement rather than replace the SQLite `events` and `llm_calls`
tables: stderr is for process operations, while the database remains the
replayable scientific and economic audit trail.

## Using real LLMs

The production profile is [runs/production.yaml](runs/production.yaml). It keeps
the PRD's cheap-citizen/strong-seat split while using the providers' current
official model IDs: Token Plan `MiniMax-M3` and Kimi Code's stable `kimi-for-coding`
alias (currently K2.7 Code when Thinking is enabled).
See the official [MiniMax Token Plan](https://platform.minimax.io/subscribe/token-plan)
and [Kimi Code API](https://www.kimi.com/code/docs/en/) documentation. The
secret-safe results of the authenticated 100-agent smoke run are recorded in
[docs/live-provider-validation.md](docs/live-provider-validation.md).

```bash
copy .env.example .env
# Fill MINIMAX_API_KEY with a Token Plan key (sk-cp-*) and KIMI_API_KEY
# with a Kimi Code membership key (sk-kimi-*), then validate without inference:
python run.py --preflight

# Optional live authentication/model-list check. This calls /models, not chat completion:
python run.py --preflight-live

# Start the approximately 100-agent production world:
python run.py
```

The no-argument entrypoint intentionally selects `runs/production.yaml`, the
locked PRD profile. Use `--config runs/base.yaml` whenever an offline scripted
run is desired; production never silently falls back when keys are absent.
The production profile records spend without a dollar ceiling; `runs/base.yaml`
retains the $200 governor cap for deterministic capped-run development.

Provider/model names are validated before genesis. A missing key, unknown route,
or unavailable model produces a clear preflight failure; it never silently falls
back to scripted behavior. HTTP 429 throttling and explicit provider-overload
responses such as MiniMax HTTP 529 create a visible provider-wide cooldown and
retry until recovery or operator stop; other network failures use
the configured bounded retry count. A continuing non-rate-limit failure records
a diagnostic, reconciles the ledger, checkpoints the last completed tick plus
the active phase cursor, and pauses visibly. Kimi receives a stable
`prompt_cache_key`, and cost accounting uses cache-hit tokens reported by the
provider rather than an estimated local cache hit.

### Production acceptance

Production acceptance is a separate evidence-gated workflow. The live command
uses an uncapped provider budget and must not start without explicit inference
approval; provider rate limits control throughput and actual spend is recorded:

```bash
# Free full-horizon rehearsal (all inherited routes are forced to scripted):
python run.py --config runs/acceptance/rehearsal.yaml --acceptance-run \
  --experiment-evidence reports/out/experiment_rumor_vs_control.json

# Paid production acceptance:
python run.py --config runs/acceptance/production.yaml --preflight-live
python run.py --config runs/acceptance/production.yaml --acceptance-run --approve-live-inference
python run.py --experiment runs/experiments/rumor_vs_control.yaml
python run.py --acceptance-report RUN_ID \
  --experiment-evidence reports/out/experiment_rumor_vs_control.json \
  --phenomena-evidence runs/acceptance/phenomena.RUN_ID.yaml
```

The receipt is written as `reports/out/acceptance_RUN_ID.{json,md}`. Copy
`runs/acceptance/phenomena.template.yaml` to a run-specific reviewed file and
replace its pending examples with three phenomena actually visible in that
run's persisted metrics.

Routing is `role → {provider, model}` — citizens on MiniMax, the high-leverage
seats (central banker, credit officers, reporters/editors, VC partner, Oracle) on
Kimi. The Claude CLI adapter is **hard-restricted in code** to Oracle/dev use.

Capped profiles retain PRD R7's staged degradation at 60/80/95% of their world
budget (fewer conversations → stretched cadences → institutional-only) and a
clean pause at 100%. The production profile explicitly disables that dollar
ceiling; its dashboard and reports show actual spend as uncapped.

## What you can do from the dashboard

- **Run controls**: start / pause / step / speed; automatic checkpoints and
  phase-aware restart from the exact interrupted phase.
- **Watch**: macro metrics (GDP proxy, CPI, unemployment, index, money supply,
  Gini, sentiment), live stock ticker, news feed (two outlets with opposite
  slants), conversation stream, bank balance sheets, cost meter.
- **Inspect**: click any agent → persona, accounts, loans, beliefs, memories, and
  the exact prompt/response behind each decision.
- **Ask the Oracle**: "probability of a bank run within 30 ticks?" → probability +
  drivers + machine-checkable resolution rule; bounded read-only evidence is
  stored with the prediction, outcomes auto-resolve, and current/pooled
  reliability curves plus Brier decomposition accumulate in the dashboard.
- **Inject shocks**: policy-rate override, oil/commodity shock, false rumor,
  slanted-news directive, firm scandal — instant, trend, or metric-conditional.
- **Export**: the standalone HTML report embeds the complete charts and the
  Markdown reviewer companion carries metrics, calibration, costs, config, and seed.

## The rumor → bank run pipeline (the point of the whole thing)

Inject a false rumor about a bank and watch it propagate: targeted agents *hear*
it (memory) → trust beliefs fall → depositors move money out (`move_deposits`) →
cross-bank reserve settlement drains the target's reserves → interbank borrowing →
central-bank lender-of-last-resort → failure with depositor haircuts if support
fails. No engine rule maps rumor → outflow; the path runs entirely through agent
beliefs and decisions. In the default world, a 20-agent rumor cuts the target
bank's deposits roughly in half within 10 ticks.

## Layout

```
run.py                  entrypoint
runs/base.yaml          world config (population, models, budget, shocks, seed)
runs/production.yaml    current MiniMax/Kimi production routing (~100 agents)
engine/                 deterministic core: ledger, exchange, credit, firms, labor, lifecycle, actions
agents/                 personas (vendored census-based gen), memory, scheduler, prompts, scripted policies
llm/                    gateway: routing, budget governor, adapters (scripted/openai_compat/anthropic/cli)
world/                  genesis, tick loop, metrics, shocks, newsroom, conversations
oracle/                 analyst, resolution rules, resolver, Brier scoring
dashboard/              React + Vite + Tailwind + Recharts dashboard source
server/                 FastAPI + WebSocket + committed production dashboard bundle
reports/                end-of-run HTML/Markdown generator
tests/                  engine invariants, scripted bank run, governor, determinism, rumor pilot
data/runs/<id>.db       one SQLite file per run (the whole run is one portable file)
```

The dashboard follows the locked React/Vite/Tailwind/Recharts stack. Scripted
policies remain the intentional offline/test profile; the production profile
uses the current real-provider routes after key and live-model preflight.

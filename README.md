# Agent Economy

[![CI](https://github.com/alinojoumi8/agent-economy/actions/workflows/ci.yml/badge.svg)](https://github.com/alinojoumi8/agent-economy/actions/workflows/ci.yml)

A living, miniature US-style economy populated by ~100 persona-driven agents —
teachers, founders, bankers, journalists — who work, trade, borrow, gossip, and
panic. **LLMs propose, a deterministic engine disposes**: every dollar flows
through a double-entry ledger that reconciles to zero every tick, so crashes and
bank runs are *real* within the sim. Start with the
[documentation index](docs/README.md), or read [PRD.md](PRD.md) and
[TECH-SPEC.md](TECH-SPEC.md) for the normative product and technical design.

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
npm run dev
# production bundle: npm run build
```

Vite proxies `/api`, `/ws`, and `/reports` to FastAPI during development. The
production bundle is committed so normal Python users still start the complete
application with one command and no Node.js runtime.

## Using real LLMs

The active [runs/production.yaml](runs/production.yaml) routes every role,
conversation, memory task, and Oracle request to Token Plan `MiniMax-M3`.
Kimi is disabled from the default runtime for now. The locked PRD mix remains
available only through the explicit [runs/production-k2.6.yaml](runs/production-k2.6.yaml)
profile. Kimi Code membership cannot select K2.6; the separate
[runs/production-kimi-code.yaml](runs/production-kimi-code.yaml) retains its
stable `kimi-for-coding` compatibility route. See the official
[MiniMax Token Plan](https://platform.minimax.io/subscribe/token-plan),
[Kimi K2.6 API](https://platform.moonshot.ai/docs/guide/kimi-k2-6-quickstart),
and [Kimi Code API](https://www.kimi.com/code/docs/en/) documentation.

```bash
copy .env.example .env
# Fill MINIMAX_API_KEY with a Token Plan key (sk-cp-*). KIMI_API_KEY is not
# required by the active default.
python run.py --preflight

# Optional live authentication/model-list check. This calls /models, not chat completion:
python run.py --preflight-live

# Start the approximately 100-agent production world:
python run.py

# Explicit PRD acceptance profile (inactive unless selected):
python run.py --config runs/production-k2.6.yaml --preflight-live

# Kimi Code membership users validate and run its stable latest-model alias:
python run.py --config runs/production-kimi-code.yaml --preflight-live
python run.py --config runs/production-kimi-code.yaml
```

The no-argument entrypoint intentionally selects the MiniMax-only
`runs/production.yaml`. Use `--config runs/base.yaml` for offline scripted runs.
Kimi never becomes active unless a Kimi profile is selected explicitly, and no
profile silently falls back to another provider or credential service.

Provider/model names are validated before genesis. A missing key, unknown route,
or unavailable model produces a clear preflight failure; it never silently falls
back to scripted behavior. During a run, network calls retry once. A continuing
provider failure records a diagnostic, reconciles the ledger, checkpoints the
partial tick, and pauses visibly. Kimi receives a stable `prompt_cache_key`, and
cost accounting uses cache-hit tokens reported by the provider rather than an
estimated local cache hit.

Routing is `role → {provider, model}`. The active profile routes every role and
purpose to MiniMax M3. The explicit K2.6 acceptance profile routes high-leverage
seats to Kimi Platform, and the Kimi Code profile uses its membership alias.
The Claude CLI adapter is **hard-restricted in code** to Oracle/dev use.

Cost governance (PRD R7): a hard cap (default $200) with staged degradation at
60/80/95% of the world budget (fewer conversations → stretched cadences →
institutional-only) and a clean pause at 100%. The Oracle has a reserved
carve-out so asking questions never starves the world.

## What you can do from the dashboard

- **Run controls**: start / pause / step / speed; automatic checkpoints.
- **Watch**: macro metrics (GDP proxy, CPI, unemployment, index, money supply,
  Gini, sentiment), live stock ticker, news feed (two outlets with opposite
  slants), conversation stream, bank balance sheets, cost meter.
- **Inspect**: click any agent → persona, accounts, loans, beliefs, memories, and
  the exact prompt/response behind each decision.
- **Ask the Oracle**: "probability of a bank run within 30 ticks?" → probability +
  drivers + machine-checkable resolution rule; predictions auto-resolve and Brier
  scores accumulate (read-only — it can never influence the world).
- **Inject shocks**: policy-rate override, oil/commodity shock, false rumor,
  slanted-news directive, firm scandal — instant, trend, or metric-conditional.

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
runs/production.yaml    active MiniMax M3-only production routing (~100 agents)
runs/production-k2.6.yaml locked MiniMax M3 + Kimi K2.6 acceptance routing
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

## Documentation

The maintained handbook covers [getting started](docs/getting-started.md),
[architecture](docs/architecture.md), [configuration](docs/configuration.md),
[operations](docs/operator-runbook.md), [API usage](docs/api-reference.md),
[development](docs/development.md), and
[troubleshooting](docs/troubleshooting.md). Contribution expectations are in
[CONTRIBUTING.md](CONTRIBUTING.md).

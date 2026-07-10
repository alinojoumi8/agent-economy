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

# Observatory: dashboard + world in one process (world starts paused — press ▶ Run)
python run.py --config runs/base.yaml
# → http://127.0.0.1:8000

# Headless: run N ticks, emit an end-of-run report, exit
python run.py --config runs/base.yaml --ticks 30

# Resume a paused/checkpointed run · exact replay (no API cost)
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
`.env.example` when configuring an optional real-model provider; the default
scripted provider remains fully offline and needs no key.

**No API key needed.** The default config routes every role to the built-in
`scripted` provider — deterministic policy agents that shop, work, lend, reprice,
spread rumors, and run on banks. The whole system (dashboard, Oracle, shocks,
reports, replay) works offline and reproducibly. Same seed ⇒ identical event log.

## Using real LLMs

Uncomment the `providers`/`routes` block in [runs/base.yaml](runs/base.yaml) and
export the matching API keys (`MINIMAX_API_KEY`, `MOONSHOT_API_KEY`, …). Routing
is `role → {provider, model}` — citizens on a cheap model, the ~8 high-leverage
seats (central banker, credit officers, editors, Oracle) on a strong one. The
Claude CLI adapter is **hard-restricted in code** to Oracle/dev use.

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
engine/                 deterministic core: ledger, exchange, credit, firms, labor, lifecycle, actions
agents/                 personas (vendored census-based gen), memory, scheduler, prompts, scripted policies
llm/                    gateway: routing, budget governor, adapters (scripted/openai_compat/anthropic/cli)
world/                  genesis, tick loop, metrics, shocks, newsroom, conversations
oracle/                 analyst, resolution rules, resolver, Brier scoring
server/                 FastAPI + WebSocket + static dashboard (zero build step)
reports/                end-of-run HTML/Markdown generator
tests/                  engine invariants, scripted bank run, governor, determinism, rumor pilot
data/runs/<id>.db       one SQLite file per run (the whole run is one portable file)
```

Two pragmatic deviations from TECH-SPEC.md, both isolated: the dashboard is a
zero-build static page instead of React+Vite (the REST/WS API is UI-agnostic, so a
React app can replace it without server changes), and scripted policies stand in
for LLM decisions until you configure providers (the spec's own build order:
prove the economy's plumbing first).

# Agent Economy — agent routing

Short routing surface only; follow the linked docs for detail.

## Run

```bash
python run.py --config runs/base.yaml
```

Deterministic, provider-free mechanics profile; safe default for local work.

## Test

Focused suite used by `.github/workflows/ci.yml` (smoke job):

```bash
python -m pytest -q tests/test_documentation.py tests/test_external_agent_gateway.py tests/test_research_export.py tests/test_prd_completion.py tests/test_recorded_replay_golden.py
```

Full local gate and dashboard commands: [docs/development.md](docs/development.md).

## Mutation boundary

- Keep all economic mutation in `engine/` or deterministic `world/` mechanics; route every monetary effect through the ledger.
- Run databases are scientific artifacts: prefer additive columns/tables; new semantics that change historical output must be gated by `engine_semantics_version`.
- v1/v2 replay behavior must remain exact; never rewrite a stored source run during replay.
- Add success, rejection, replay, and reconciliation tests for new behavior.

## Docs

- Development, test layers, schema compatibility: [docs/development.md](docs/development.md)
- Contribution and review expectations: [CONTRIBUTING.md](CONTRIBUTING.md)
- Dashboard/frontend work: [DESIGN.md](DESIGN.md)

## Imported Claude Cowork project instructions

<!-- graft:start -->
## Graft — repo context graph

This repo is indexed in `graft/`: small linked markdown nodes that explain each
system and carry exact file:line spans, kept in sync with the code through git.

For ANY task here — understanding how something works, finding where code lives,
or scoping a change — get context from the graph before grepping or opening
source files. Re-ask freely (it's cheap) and reuse literal identifiers you
already have (symbol, error string, file name) as the query. New to this repo?
Run `graft map` first — a token-budgeted orientation (dir clusters, hubs,
hotspots), no LLM, no key.

- Run `graft ask "<your question>" --source` → ranked nodes with the relevant
  code spans inlined (each hit's ≤8-line crux by default; `--full` for whole
  definitions when the crux isn't enough). Match the tool to the task shape:
  for understanding or editing, the top node IS the answer — cite its
  `covers:` file:line spans and edit straight from `--source`. For
  exhaustive tasks ("every occurrence / every caller of this pattern"), ranked
  results are top-N, not complete — run `graft grep "<literal>"` instead
  (exhaustive over indexed files, grouped by enclosing symbol), falling back
  to raw `grep -rn` only for unindexed files.
- `graft skeleton <file>` → every definition's signature + span, ~10× cheaper
  than reading the file; use it to skim an API surface.
- `graft callers <symbol>` gives precomputed, exact edges — who calls this.
  Add `--direction out` for what it calls, or `--depth N` to walk
  transitively for the full blast radius. For structural questions, skip
  ranking and use this directly.
- Or browse: `graft/INDEX.md` lists every node; follow the links.
- Monorepos and folders of multiple repos rank fairly across sub-projects —
  hits carry `[scope/]` labels naming which one they're from. Narrow with
  `graft ask "<task>" --in <scope>/` once you know where you're working.

If a returned span is truncated ("+N more lines"), open the file at that exact
range before finalizing. Only open source files when a node genuinely lacks a
needed detail, and then at the exact file:line the node points to — never
re-read whole files.

After big code changes, refresh the graph with `graft build` (deterministic,
no API key, $0).
<!-- graft:end -->

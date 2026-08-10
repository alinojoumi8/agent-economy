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
